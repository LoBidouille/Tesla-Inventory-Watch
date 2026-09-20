"""Data coordinator for Tesla Inventory Watch."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TeslaInventoryApi, TeslaInventoryError, TeslaInventoryRateLimited
from .const import (
    CONF_INTERVAL,
    CONF_MODEL,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
    DOMAIN,
    EVENT_NEW_VEHICLE,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)


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
        )
        self._previous_vins: set[str] = set()
        self._stored_signature: str | None = None
        self._initialized = False

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            config_entry=entry,
            update_interval=timedelta(minutes=int(config[CONF_INTERVAL])),
        )

    async def _async_setup(self) -> None:
        stored = await self._store.async_load()
        if isinstance(stored, dict):
            self._previous_vins = set(stored.get("current_vins") or [])
            self._stored_signature = stored.get("signature")
            self._initialized = bool(stored.get("initialized", False))

    async def _save_state(self, current_vins: set[str], signature: str) -> None:
        await self._store.async_save(
            {
                "initialized": True,
                "current_vins": sorted(current_vins),
                "signature": signature,
            }
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            inventory = await self.api.async_get_inventory()
        except TeslaInventoryRateLimited as err:
            raise UpdateFailed(
                "Tesla rate limit reached",
                retry_after=err.retry_after,
            ) from err
        except TeslaInventoryError as err:
            raise UpdateFailed(f"Tesla inventory request failed: {err}") from err

        vehicles: list[dict[str, Any]] = inventory["vehicles"]
        current_vins = {str(car["vin"]) for car in vehicles if car.get("vin")}
        signature = self.api.signature
        new_vehicles: list[dict[str, Any]] = []
        baseline_reset = False

        if (
            not self._initialized
            or self._stored_signature is None
            or self._stored_signature != signature
        ):
            # First start or filters changed: establish a silent baseline.
            self._previous_vins = current_vins
            self._stored_signature = signature
            self._initialized = True
            baseline_reset = True
            await self._save_state(current_vins, signature)

        else:
            new_vins = current_vins - self._previous_vins

            if new_vins:
                by_vin = {str(car["vin"]): car for car in vehicles if car.get("vin")}
                new_vehicles = [by_vin[vin] for vin in sorted(new_vins) if vin in by_vin]

            # Protect against a transient empty Tesla response.
            if current_vins or not self._previous_vins:
                self._previous_vins = current_vins
                await self._save_state(current_vins, signature)

        for vehicle in new_vehicles:
            self.hass.bus.async_fire(EVENT_NEW_VEHICLE, vehicle)

        if new_vehicles and self.config.get(CONF_NOTIFY_ENABLED, False):
            await self._async_send_notifications(new_vehicles)

        return {
            "total": int(inventory["total"]),
            "vehicles": vehicles,
            "new_vehicles": new_vehicles,
            "baseline_reset": baseline_reset,
        }

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
