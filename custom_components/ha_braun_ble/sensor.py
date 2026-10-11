"""Sensor platform for Braun Health BLE integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import BraunDataUpdateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Braun BLE sensors based on a config entry."""
    coordinator: BraunDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = [
        BraunTemperatureSensor(coordinator),
        BraunBatterySensor(coordinator),
        BraunRecordCountSensor(coordinator),
    ]

    async_add_entities(entities)


class BraunEntity(CoordinatorEntity[BraunDataUpdateCoordinator]):
    """Base class for Braun BLE entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BraunDataUpdateCoordinator, key: str) -> None:
        """Initialize Braun entity."""
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=coordinator.entry.title,
            manufacturer="Braun (Kaz / Helen of Troy)",
            model=coordinator.profile.name,
        )


class BraunTemperatureSensor(BraunEntity, SensorEntity):
    """Sensor for the latest body temperature reading."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_translation_key = "temperature"
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator: BraunDataUpdateCoordinator) -> None:
        """Initialize temperature sensor."""
        super().__init__(coordinator, "temperature")

    @property
    def native_value(self) -> float | None:
        """Return the current temperature value."""
        return self.coordinator.data.get("temperature")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional metadata from the latest measurement."""
        rec = self.coordinator.data.get("latest_record") or {}
        return {
            "age_group": self.coordinator.data.get("age_group"),
            "fever_status": self.coordinator.data.get("fever_status"),
            "measured_at": rec.get("timestamp"),
            "record_index": rec.get("record_index"),
            "last_synced": self.coordinator.data.get("last_synced"),
            "raw_hex": rec.get("raw_hex"),
        }


class BraunBatterySensor(BraunEntity, SensorEntity):
    """Sensor for thermometer battery percentage."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_translation_key = "battery"

    def __init__(self, coordinator: BraunDataUpdateCoordinator) -> None:
        """Initialize battery sensor."""
        super().__init__(coordinator, "battery")

    @property
    def native_value(self) -> int | None:
        """Return the battery percentage."""
        return self.coordinator.data.get("battery")


class BraunRecordCountSensor(BraunEntity, SensorEntity):
    """Sensor for the total number of records stored on the device."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_translation_key = "stored_records"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: BraunDataUpdateCoordinator) -> None:
        """Initialize records count sensor."""
        super().__init__(coordinator, "record_count")

    @property
    def native_value(self) -> int | None:
        """Return number of stored records."""
        return self.coordinator.data.get("record_count")
