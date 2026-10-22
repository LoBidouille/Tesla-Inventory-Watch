"""Data coordinator for Tesla Inventory Watch."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
import logging
import math
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TeslaInventoryApi, TeslaInventoryError, TeslaInventoryRateLimited
from .const import (
    CONF_MODEL,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
    DOMAIN,
    EVENT_NEW_VEHICLE,
    STORAGE_VERSION,
    POLL_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)


def _verify_saved_state(path: str, expected: dict[str, Any]) -> None:
    with open(path, encoding="utf-8") as stream:
        saved = json.load(stream)
    if saved.get("data") != expected:
        raise OSError("Tesla polling checkpoint could not be saved")


class TeslaInventoryCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinate inventory polling and new VIN detection."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: TeslaInventoryApi,
        config: dict[str, Any],
    ) -> None:
        self.entry = entry
        self.api = api
        self.config = config
        self._store = Store(
            hass,
            STORAGE_VERSION,
            f"{DOMAIN}.{entry.entry_id}",
            atomic_writes=True,
        )
        self._previous_vins: set[str] = set()
        self._stored_signature: str | None = None
        self._initialized = False
        self._next_attempt = 0.0
        self._last_error: str | None = None
        self._cached_data: dict[str, Any] | None = None
        self._poll_lock = asyncio.Lock()

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            config_entry=entry,
            update_interval=timedelta(seconds=POLL_INTERVAL_SECONDS),
        )

    async def _async_setup(self) -> None:
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._previous_vins = set(stored.get("current_vins") or [])
            self._stored_signature = stored.get("signature")
            self._initialized = bool(stored.get("initialized", False))
            self._next_attempt = float(stored.get("next_attempt", 0))
            self._last_error = stored.get("last_error")
            cached = stored.get("cached_data")
            if isinstance(cached, dict) and isinstance(cached.get("vehicles"), list):
                self._cached_data = cached

    def _state(self) -> dict[str, Any]:
        return {
            "initialized": self._initialized,
            "current_vins": sorted(self._previous_vins),
            "signature": self._stored_signature,
            "next_attempt": self._next_attempt,
            "last_error": self._last_error,
            "cached_data": self._cached_data,
        }

    async def _async_save_state(self, state: dict[str, Any]) -> None:
        await self._store.async_save(state)
        # Store logs some disk-write failures without raising them. Verify the
        # checkpoint before sending a request or consuming notification state.
        await self._async_verify_saved_state(state)

    async def _async_verify_saved_state(self, state: dict[str, Any]) -> None:
        await self.hass.async_add_executor_job(_verify_saved_state, self._store.path, state)

    def _remaining(self) -> int:
        remaining = max(1, math.ceil(self._next_attempt - time.time()))
        self.update_interval = timedelta(seconds=remaining)
        return remaining

    async def _async_update_data(self) -> dict[str, Any]:
        # A manual refresh, reload or failed setup must not bypass the budget.
        async with self._poll_lock:
            return await self._async_poll()

    async def _async_poll(self) -> dict[str, Any]:
        if time.time() < self._next_attempt:
            remaining = self._remaining()
            if (
                self._cached_data is not None
                and self._stored_signature == self.api.signature
                and self._last_error is None
            ):
                # Retained data may be displayed, but never resend old alerts.
                return {**self._cached_data, "new_vehicles": [], "baseline_reset": False}
            raise UpdateFailed(
                self._last_error or "Next Tesla check is not due yet",
                retry_after=remaining,
            )

        # Reserve and persist the attempt BEFORE any network operation, including
        # failures and cancellation. Restarting HA does not reset the eight hours.
        next_attempt = time.time() + POLL_INTERVAL_SECONDS
        await self._async_save_state({
            **self._state(),
            "next_attempt": next_attempt,
            "last_error": "Previous Tesla check did not complete",
        })
        self._next_attempt = next_attempt
        self._last_error = "Previous Tesla check did not complete"
        try:
            inventory = await self.api.async_get_inventory()
        except TeslaInventoryError as err:
            if isinstance(err, TeslaInventoryRateLimited):
                self._next_attempt = max(self._next_attempt, time.time() + err.retry_after)
            self._last_error = f"Tesla inventory request failed: {err}"
            await self._async_save_state(self._state())
            raise UpdateFailed(self._last_error, retry_after=self._remaining()) from err

        vehicles: list[dict[str, Any]] = inventory["vehicles"]
        current_vins = {str(car["vin"]) for car in vehicles if car.get("vin")}
        signature = self.api.signature
        new_vehicles: list[dict[str, Any]] = []
        baseline_reset = (
            not self._initialized
            or self._stored_signature is None
            or self._stored_signature != signature
        )
        if not baseline_reset:
            new_vins = current_vins - self._previous_vins
            by_vin = {str(car["vin"]): car for car in vehicles if car.get("vin")}
            new_vehicles = [by_vin[vin] for vin in sorted(new_vins)]

        # Protect the baseline against a transient empty Tesla response.
        baseline = (
            current_vins
            if baseline_reset or current_vins or not self._previous_vins
            else self._previous_vins
        )
        data = {
            "total": int(inventory["total"]),
            "vehicles": vehicles,
            "new_vehicles": new_vehicles,
            "baseline_reset": baseline_reset,
            "last_checked": time.time(),
            "next_check": self._next_attempt,
        }
        await self._async_save_state({
            **self._state(),
            "initialized": True,
            "current_vins": sorted(baseline),
            "signature": signature,
            "cached_data": data,
            "last_error": None,
        })
        self._previous_vins = baseline
        self._stored_signature = signature
        self._initialized = True
        self._cached_data = data
        self._last_error = None
        self._remaining()

        for vehicle in new_vehicles:
            self.hass.bus.async_fire(EVENT_NEW_VEHICLE, vehicle)
        if new_vehicles and self.config.get(CONF_NOTIFY_ENABLED, False):
            await self._async_send_notifications(new_vehicles)
        return data

    async def _async_send_notifications(
        self,
        vehicles: list[dict[str, Any]],
    ) -> None:
        service_name = str(self.config.get(CONF_NOTIFY_SERVICE, "")).strip()
        if service_name.startswith("notify."):
            service_name = service_name.split(".", 1)[1]

        if not service_name:
            _LOGGER.warning("Notifications enabled but no notify service selected")
            return

        model_label = {
            "m3": "Model 3",
            "my": "Model Y",
            "ms": "Model S",
            "mx": "Model X",
        }.get(str(self.config.get(CONF_MODEL)), "Tesla")

        for vehicle in vehicles:
            parts: list[str] = []

            if vehicle.get("year"):
                parts.append(str(vehicle["year"]))
            if vehicle.get("trim"):
                parts.append(str(vehicle["trim"]))

            price = vehicle.get("price")
            if isinstance(price, (int, float)):
                parts.append(f"{price:,.0f} €".replace(",", " "))

            mileage = vehicle.get("mileage")
            if isinstance(mileage, (int, float)):
                parts.append(f"{mileage:,.0f} km".replace(",", " "))

            if vehicle.get("city"):
                parts.append(str(vehicle["city"]))

            service_data: dict[str, Any] = {
                "title": f"🚗 Nouvelle Tesla {model_label}",
                "message": " • ".join(parts) or f"Nouveau VIN {vehicle['vin']}",
            }

            # Rich mobile-app notification when the selected service is a mobile app.
            if service_name.startswith("mobile_app_") and vehicle.get("url"):
                service_data["data"] = {
                    "url": vehicle["url"],
                    "actions": [
                        {
                            "action": "URI",
                            "title": "Voir sur Tesla",
                            "uri": vehicle["url"],
                        }
                    ],
                }

            try:
                await self.hass.services.async_call(
                    "notify",
                    service_name,
                    service_data,
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Unable to send Tesla inventory notification via notify.%s",
                    service_name,
                )
