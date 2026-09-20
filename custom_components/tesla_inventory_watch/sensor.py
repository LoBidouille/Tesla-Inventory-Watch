"""Sensors for Tesla Inventory Watch."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
    """Set up Tesla inventory sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            TeslaInventoryAvailableSensor(coordinator, entry),
            TeslaInventoryNewSensor(coordinator, entry),
        ]
    )


class TeslaInventoryBaseSensor(
    CoordinatorEntity[TeslaInventoryCoordinator],
    SensorEntity,
):
    """Base Tesla inventory sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TeslaInventoryCoordinator,
        entry: TeslaInventoryConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Tesla Inventory Watch",
            manufacturer="Community integration",
            model="Tesla inventory monitor",
        )


class TeslaInventoryAvailableSensor(TeslaInventoryBaseSensor):
    """Number of matching vehicles."""

    _attr_translation_key = "available"
    _attr_icon = "mdi:car-multiple"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_available"

    @property
    def native_value(self) -> int:
        return int(self.coordinator.data.get("total", 0))

    @property
    def extra_state_attributes(self):
        vehicles = self.coordinator.data.get("vehicles", [])
        return {
            "vins": [car.get("vin") for car in vehicles if car.get("vin")],
            "baseline_reset": bool(self.coordinator.data.get("baseline_reset", False)),
        }


class TeslaInventoryNewSensor(TeslaInventoryBaseSensor):
    """Number of new vehicles detected on the last poll."""

    _attr_translation_key = "new"
    _attr_icon = "mdi:car-arrow-right"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_new"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("new_vehicles", []))

    @property
    def extra_state_attributes(self):
        return {
            "vehicles": self.coordinator.data.get("new_vehicles", []),
        }
