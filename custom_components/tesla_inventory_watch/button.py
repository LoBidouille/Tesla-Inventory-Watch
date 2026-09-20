"""Buttons for Tesla Inventory Watch."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TeslaInventoryConfigEntry
from .const import DOMAIN
from .coordinator import TeslaInventoryCoordinator


async def async_setup_entry(
    hass,
    entry: TeslaInventoryConfigEntry,
    async_add_entities,
) -> None:
    """Set up Tesla inventory button."""
    async_add_entities([TeslaInventoryRefreshButton(entry.runtime_data.coordinator, entry)])


class TeslaInventoryRefreshButton(
    CoordinatorEntity[TeslaInventoryCoordinator],
    ButtonEntity,
):
    """Manual refresh button."""

    _attr_has_entity_name = True
    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Tesla Inventory Watch",
            manufacturer="Community integration",
            model="Tesla inventory monitor",
        )

    async def async_press(self) -> None:
        """Refresh inventory now."""
        await self.coordinator.async_request_refresh()
