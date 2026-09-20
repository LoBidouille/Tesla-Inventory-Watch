"""Tesla Inventory Watch integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
    config.setdefault(CONF_INTERVAL, DEFAULT_INTERVAL)
    config.setdefault(CONF_NOTIFY_ENABLED, DEFAULT_NOTIFY_ENABLED)
    config.setdefault(CONF_NOTIFY_SERVICE, DEFAULT_NOTIFY_SERVICE)

    api = TeslaInventoryApi(async_get_clientsession(hass), config)
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
