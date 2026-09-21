"""Tesla inventory API client."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from curl_cffi.requests import AsyncSession

from .const import (
    CONF_CATEGORIES,
    CONF_CONDITION,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MODEL,
    CONF_ODOMETER_MAX,
    CONF_ODOMETER_MIN,
    CONF_ORDER,
    CONF_PAINTS,
    CONF_PRICE_MAX,
    CONF_PRICE_MIN,
    CONF_RANGE,
    CONF_SORT,
    CONF_YEARS,
    CONF_ZIP,
    TESLA_API,
    TESLA_INVENTORY_BASE,
)


class TeslaInventoryError(Exception):
    """Base Tesla inventory exception."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class TeslaInventoryRateLimited(TeslaInventoryError):
    """Tesla rate limit exception."""

    def __init__(self, retry_after: int = 300) -> None:
        super().__init__("Tesla rate limit reached", status=429)
        self.retry_after = retry_after


class TeslaInventoryApi:
    """Small client for Tesla's inventory endpoint."""

    def __init__(self, session: Any, config: dict[str, Any]) -> None:
        # Home Assistant's aiohttp session is intentionally not used here.
        # Tesla may reject its TLS/HTTP fingerprint with HTTP 403.
        self._config = config

    @property
    def model(self) -> str:
        return str(self._config[CONF_MODEL])

    @property
    def condition(self) -> str:
        return str(self._config[CONF_CONDITION])

    @property
    def signature(self) -> str:
        """Hash only inventory-affecting settings."""
        raw = json.dumps(
            self._query_payload(0, 24),
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _query_payload(self, offset: int, count: int) -> dict[str, Any]:
        options: dict[str, Any] = {}

        categories = [str(v) for v in self._config.get(CONF_CATEGORIES, []) if v]
        years = [
            int(v)
            for v in self._config.get(CONF_YEARS, [])
            if str(v).isdigit()
        ]
        paints = [str(v) for v in self._config.get(CONF_PAINTS, []) if v]

        if categories:
            options["CATEGORY"] = categories
        if years:
            options["Year"] = years
        if paints:
            options["PAINT"] = paints

        query: dict[str, Any] = {
            "model": self.model,
            "condition": self.condition,
            "options": options,
            "arrangeby": self._config.get(CONF_SORT, "Price"),
            "order": self._config.get(CONF_ORDER, "asc"),
            "market": "FR",
            "language": "fr",
            # Tesla's browser request encodes this space as "+" in the URL.
            "super_region": "north america",
            "PaymentType": "cash",
            "paymentRange": (
                f"{int(self._config[CONF_PRICE_MIN])},"
                f"{int(self._config[CONF_PRICE_MAX])}"
            ),
            "Odometer": (
                f"{int(self._config[CONF_ODOMETER_MIN])},"
                f"{int(self._config[CONF_ODOMETER_MAX])}"
            ),
            "lng": float(self._config[CONF_LONGITUDE]),
            "lat": float(self._config[CONF_LATITUDE]),
            "zip": str(self._config[CONF_ZIP]),
            "range": int(self._config[CONF_RANGE]),
            "region": "FR",
        }

        return {
            "query": query,
            "offset": offset,
            "count": count,
            "outsideOffset": 0,
            "outsideSearch": False,
            "isFalconDeliverySelectionEnabled": False,
            "version": None,
        }

    def _referer(self) -> str:
        return f"{TESLA_INVENTORY_BASE}/{self.condition}/{self.model}"

    async def async_get_inventory(self) -> dict[str, Any]:
        """Fetch matching vehicles while impersonating a normal browser."""
        page_size = 24
        offset = 0
        all_results: list[dict[str, Any]] = []
        total: int | None = None
        referer = self._referer()

        browser_headers = {
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }

        api_headers = {
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Referer": referer,
            "Origin": "https://www.tesla.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        try:
            async with AsyncSession() as browser:
                # Establish the same type of session/cookies as the inventory page.
                # A failure on this warm-up request is not fatal by itself.
                try:
                    await browser.get(
                        referer,
                        headers=browser_headers,
                        impersonate="chrome",
                        timeout=30,
                        allow_redirects=True,
                    )
                except Exception:
                    pass

                # Safety cap: 4 x 24 = 96 matching vehicles.
                for _ in range(4):
                    payload = self._query_payload(offset, page_size)

                    response = await browser.get(
                        TESLA_API,
                        params={
                            "query": json.dumps(
                                payload,
                                separators=(",", ":"),
                            )
                        },
                        headers=api_headers,
                        impersonate="chrome",
                        timeout=30,
                        allow_redirects=True,
                    )

                    status = int(response.status_code)

                    if status == 429:
                        retry_header = response.headers.get("Retry-After", "")
                        try:
                            retry_after = max(
                                60,
                                min(3600, int(retry_header)),
                            )
                        except (TypeError, ValueError):
                            retry_after = 300
                        raise TeslaInventoryRateLimited(retry_after)

                    if status < 200 or status >= 300:
                        body = (response.text or "")[:300].replace("\n", " ")
                        raise TeslaInventoryError(
                            f"HTTP {status}: {body or 'réponse refusée par Tesla'}",
                            status=status,
                        )

                    try:
                        data = response.json()
                    except Exception as err:
                        body = (response.text or "")[:300].replace("\n", " ")
                        raise TeslaInventoryError(
                            f"Réponse Tesla non JSON: {body or 'réponse vide'}"
                        ) from err

                    results = data.get("results")
                    if not isinstance(results, list):
                        raise TeslaInventoryError(
                            "Tesla response does not contain a results list"
                        )

                    all_results.extend(
                        item for item in results if isinstance(item, dict)
                    )

                    if total is None:
                        raw_total = data.get("total_matches_found")
                        total = (
                            int(raw_total)
                            if isinstance(raw_total, (int, float))
                            else len(results)
                        )

                    if len(results) < page_size or len(all_results) >= total:
                        break

                    offset += len(results)

        except (TeslaInventoryRateLimited, TeslaInventoryError):
            raise
        except Exception as err:
            raise TeslaInventoryError(
                f"{type(err).__name__}: {err}"
            ) from err

        vehicles = [self._normalize_vehicle(car) for car in all_results]
        vehicles = [car for car in vehicles if car.get("vin")]

        return {
            "total": total if total is not None else len(vehicles),
            "vehicles": vehicles,
        }

    def _normalize_vehicle(self, car: dict[str, Any]) -> dict[str, Any]:
        paint = ""

        for option in car.get("OptionCodeData") or []:
            if isinstance(option, dict) and option.get("group") == "PAINT":
                paint = str(
                    option.get("name")
                    or option.get("description")
                    or ""
                )
                break

        if not paint:
            raw_paint = car.get("PAINT")
            if isinstance(raw_paint, list):
                paint = ", ".join(str(v) for v in raw_paint)
            elif raw_paint:
                paint = str(raw_paint)

        vin = str(car.get("VIN") or "")
        model = self.model

        return {
            "vin": vin,
            "year": car.get("Year"),
            "trim": car.get("TrimName") or car.get("TRIM") or "",
            "price": (
                car.get("InventoryPrice")
                or car.get("PurchasePrice")
                or car.get("Price")
            ),
            "mileage": car.get("Odometer"),
            "city": car.get("City") or "",
            "region": (
                car.get("VehicleRegion")
                or car.get("StateProvinceLongName")
                or ""
            ),
            "paint": paint,
            "range_km": car.get("ActualRange"),
            "url": (
                f"https://www.tesla.com/fr_FR/{model}/order/{vin}"
                f"?redirect=no&titleStatus={self.condition}"
            )
            if vin
            else "",
        }
