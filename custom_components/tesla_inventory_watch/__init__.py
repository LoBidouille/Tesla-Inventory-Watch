"""Tesla Inventory Watch integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .api import TeslaInventoryApi
from .const import (
    CONF_INTERVAL,
    CONF_NOTIFY_ENABLED,
    CONF_NOTIFY_SERVICE,
    DEFAULT_INTERVAL,
    DEFAULT_NOTIFY_ENABLED,
    DEFAULT_NOTIFY_SERVICE,
    PLATFORMS,
)
from .coordinator import TeslaInventoryCoordinator
from .transport import async_create_browser_session


@dataclass
class TeslaInventoryRuntimeData:
    """Runtime data."""

    coordinator: TeslaInventoryCoordinator


type TeslaInventoryConfigEntry = ConfigEntry[TeslaInventoryRuntimeData]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: TeslaInventoryConfigEntry,
) -> bool:
    """Set up Tesla Inventory Watch from a config entry."""
    config: dict[str, Any] = {**entry.data, **entry.options}
    config[CONF_INTERVAL] = DEFAULT_INTERVAL
    config.setdefault(CONF_NOTIFY_ENABLED, DEFAULT_NOTIFY_ENABLED)
    config.setdefault(CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE)

    try:
        websession = await async_create_browser_session(hass)
    except (ImportError, OSError) as err:
        raise ConfigEntryNotReady(
            "Unable to load Chrome HTTP client; check curl-cffi installation"
        ) from err
    entry.async_on_unload(websession.close)
    api = TeslaInventoryApi(websession, config)
    coordinator = TeslaInventoryCoordinator(hass, entry, api, config)

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = TeslaInventoryRuntimeData(coordinator=coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: TeslaInventoryConfigEntry,
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
