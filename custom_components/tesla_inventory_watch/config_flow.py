"""Config flow for Tesla Inventory Watch."""

from __future__ import annotations

from datetime import date
from typing import Any

import voluptuous as vol
from aiohttp import CookieJar

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import TeslaInventoryApi, TeslaInventoryError, TeslaInventoryRateLimited
from .const import (
    CONF_CATEGORIES,
    CONF_CONDITION,
    CONF_INTERVAL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_MODEL,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
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
    DEFAULT_CATEGORIES,
    DEFAULT_CONDITION,
    DEFAULT_INTERVAL,
    DEFAULT_LATITUDE,
    DEFAULT_LONGITUDE,
    DEFAULT_MODEL,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_SERVICE,
    DEFAULT_ODOMETER_MAX,
    DEFAULT_ODOMETER_MIN,
    DEFAULT_ORDER,
    DEFAULT_PAINTS,
    DEFAULT_PRICE_MAX,
    DEFAULT_PRICE_MIN,
    DEFAULT_RANGE,
    DEFAULT_SORT,
    DEFAULT_YEARS,
    DEFAULT_ZIP,
    DOMAIN,
    MAX_INTERVAL,
    MIN_INTERVAL,
)


def _defaults(values: dict[str, Any] | None = None) -> dict[str, Any]:
    values = values or {}
    return {
        CONF_MODEL: values.get(CONF_MODEL, DEFAULT_MODEL),
        CONF_CONDITION: values.get(CONF_CONDITION, DEFAULT_CONDITION),
        CONF_CATEGORIES: values.get(CONF_CATEGORIES, DEFAULT_CATEGORIES),
        CONF_YEARS: values.get(CONF_YEARS, DEFAULT_YEARS),
        CONF_PAINTS: values.get(CONF_PAINTS, DEFAULT_PAINTS),
        CONF_PRICE_MIN: values.get(CONF_PRICE_MIN, DEFAULT_PRICE_MIN),
        CONF_PRICE_MAX: values.get(CONF_PRICE_MAX, DEFAULT_PRICE_MAX),
        CONF_ODOMETER_MIN: values.get(CONF_ODOMETER_MIN, DEFAULT_ODOMETER_MIN),
        CONF_ODOMETER_MAX: values.get(CONF_ODOMETER_MAX, DEFAULT_ODOMETER_MAX),
        CONF_ZIP: values.get(CONF_ZIP, DEFAULT_ZIP),
        CONF_RANGE: values.get(CONF_RANGE, DEFAULT_RANGE),
        CONF_LATITUDE: values.get(CONF_LATITUDE, DEFAULT_LATITUDE),
        CONF_LONGITUDE: values.get(CONF_LONGITUDE, DEFAULT_LONGITUDE),
        CONF_INTERVAL: values.get(CONF_INTERVAL, DEFAULT_INTERVAL),
        CONF_NOTIFY_ENABLED: values.get(CONF_NOTIFY_ENABLED, DEFAULT_NOTIFY_ENABLED),
        CONF_NOTIFY_SERVICE: values.get(CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE),
        CONF_SORT: values.get(CONF_SORT, DEFAULT_SORT),
        CONF_ORDER: values.get(CONF_ORDER, DEFAULT_ORDER),
    }


def _notification_services(hass) -> list[SelectOptionDict]:
    services = hass.services.async_services().get("notify", {})
    return [
        SelectOptionDict(value=f"notify.{name}", label=f"notify.{name}")
        for name in sorted(services)
    ]


def _schema(hass, values: dict[str, Any] | None = None) -> vol.Schema:
    cfg = _defaults(values)
    current_year = date.today().year
    year_options = [str(year) for year in range(2017, current_year + 2)]

    notify_options = _notification_services(hass)

    return vol.Schema(
        {
            vol.Required(CONF_MODEL, default=cfg[CONF_MODEL]): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="m3", label="Model 3"),
                        SelectOptionDict(value="my", label="Model Y"),
                        SelectOptionDict(value="ms", label="Model S"),
                        SelectOptionDict(value="mx", label="Model X"),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_CONDITION, default=cfg[CONF_CONDITION]): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="used", label="Occasion"),
                        SelectOptionDict(value="new", label="Neuf"),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_CATEGORIES, default=cfg[CONF_CATEGORIES]): SelectSelector(
                SelectSelectorConfig(
                    options=["LRRWD", "PRRWD", "LRAWD"],
                    multiple=True,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_YEARS, default=cfg[CONF_YEARS]): SelectSelector(
                SelectSelectorConfig(
                    options=year_options,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_PAINTS, default=cfg[CONF_PAINTS]): SelectSelector(
                SelectSelectorConfig(
                    options=["BLACK", "GREY"],
                    multiple=True,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_PRICE_MIN, default=cfg[CONF_PRICE_MIN]): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=250000, step=500, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_PRICE_MAX, default=cfg[CONF_PRICE_MAX]): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=250000, step=500, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_ODOMETER_MIN, default=cfg[CONF_ODOMETER_MIN]
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=500000, step=1000, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(
                CONF_ODOMETER_MAX, default=cfg[CONF_ODOMETER_MAX]
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=500000, step=1000, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_ZIP, default=cfg[CONF_ZIP]): str,
            vol.Required(CONF_RANGE, default=cfg[CONF_RANGE]): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=2000, step=10, mode=NumberSelectorMode.BOX
                )
            ),
            vol.Required(CONF_LATITUDE, default=cfg[CONF_LATITUDE]): vol.Coerce(float),
            vol.Required(CONF_LONGITUDE, default=cfg[CONF_LONGITUDE]): vol.Coerce(float),
            vol.Required(CONF_SORT, default=cfg[CONF_SORT]): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="Price", label="Prix"),
                        SelectOptionDict(value="Odometer", label="Kilométrage"),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_ORDER, default=cfg[CONF_ORDER]): SelectSelector(
                SelectSelectorConfig(
                    options=[
                        SelectOptionDict(value="asc", label="Croissant"),
                        SelectOptionDict(value="desc", label="Décroissant"),
                    ],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_INTERVAL, default=cfg[CONF_INTERVAL]): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_INTERVAL,
                    max=MAX_INTERVAL,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="min",
                )
            ),
            vol.Required(
                CONF_NOTIFY_ENABLED, default=bool(cfg[CONF_NOTIFY_ENABLED])
            ): bool,
            vol.Optional(
                CONF_NOTIFY_SERVICE,
                description={"suggested_value": cfg[CONF_NOTIFY_SERVICE]},
            ): SelectSelector(
                SelectSelectorConfig(
                    options=notify_options,
                    custom_value=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _validate(user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}

    if float(user_input[CONF_PRICE_MIN]) > float(user_input[CONF_PRICE_MAX]):
        errors[CONF_PRICE_MAX] = "max_lower_than_min"

    if float(user_input[CONF_ODOMETER_MIN]) > float(user_input[CONF_ODOMETER_MAX]):
        errors[CONF_ODOMETER_MAX] = "max_lower_than_min"

    if bool(user_input.get(CONF_NOTIFY_ENABLED)) and not str(
        user_input.get(CONF_NOTIFY_SERVICE, "")
    ).strip():
        errors[CONF_NOTIFY_SERVICE] = "notification_service_required"

    return errors


class TeslaInventoryConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle Tesla Inventory Watch setup."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Set up an inventory watch."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_NOTIFY_SERVICE] = str(
                user_input.get(CONF_NOTIFY_SERVICE, "")
            ).strip()
            errors = _validate(user_input)

            if not errors:
                try:
                    websession = async_create_clientsession(
                        self.hass,
                        auto_cleanup=False,
                        cookie_jar=CookieJar(),
                    )
                    try:
                        api = TeslaInventoryApi(websession, user_input)
                        await api.async_get_inventory()
                    finally:
                        websession.detach()
                except TeslaInventoryRateLimited:
                    errors["base"] = "rate_limited"
                except TeslaInventoryError as err:
                    if getattr(err, "status", None) == 403:
                        errors["base"] = "forbidden"
                    else:
                        errors["base"] = "cannot_connect"
                else:
                    model = str(user_input[CONF_MODEL]).upper()
                    zip_code = str(user_input[CONF_ZIP])
                    return self.async_create_entry(
                        title=f"Tesla {model} - {zip_code}",
                        data=user_input,
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=_schema(self.hass, user_input),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Create options flow."""
        return TeslaInventoryOptionsFlow()


class TeslaInventoryOptionsFlow(OptionsFlowWithReload):
    """Manage Tesla Inventory Watch options."""

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Edit filters, notifications and polling interval."""
        current = {**self.config_entry.data, **self.config_entry.options}
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_NOTIFY_SERVICE] = str(
                user_input.get(CONF_NOTIFY_SERVICE, "")
            ).strip()
            errors = _validate(user_input)

            if not errors:
                try:
                    websession = async_create_clientsession(
                        self.hass,
                        auto_cleanup=False,
                        cookie_jar=CookieJar(),
                    )
                    try:
                        api = TeslaInventoryApi(websession, user_input)
                        await api.async_get_inventory()
                    finally:
                        websession.detach()
                except TeslaInventoryRateLimited:
                    errors["base"] = "rate_limited"
                except TeslaInventoryError as err:
                    if getattr(err, "status", None) == 403:
                        errors["base"] = "forbidden"
                    else:
                        errors["base"] = "cannot_connect"
                else:
                    return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_schema(self.hass, user_input or current),
            errors=errors,
        )
