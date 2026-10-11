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

TEMPERATURE = SensorEntityDescription(
    key="temperature",
    translation_key="temperature",
    device_class=SensorDeviceClass.TEMPERATURE,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=UnitOfTemperature.CELSIUS,
    icon="mdi:thermometer",
)
BATTERY = SensorEntityDescription(
    key="battery",
    translation_key="battery",
    device_class=SensorDeviceClass.BATTERY,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=PERCENTAGE,
)
RECORD_COUNT = SensorEntityDescription(
    key="record_count",
    translation_key="stored_records",
    state_class=SensorStateClass.TOTAL,
    icon="mdi:counter",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Braun BLE sensors based on a config entry."""
    coordinator: BraunDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            BraunTemperatureSensor(coordinator, TEMPERATURE),
            BraunSensor(coordinator, BATTERY),
            BraunSensor(coordinator, RECORD_COUNT),
        ]
    )


class BraunSensor(CoordinatorEntity[BraunDataUpdateCoordinator], SensorEntity):
    """Sensor reading one key of the coordinator data."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BraunDataUpdateCoordinator, description: SensorEntityDescription
    ) -> None:
        """Initialize Braun sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            name=coordinator.entry.title,
            manufacturer="Braun (Kaz / Helen of Troy)",
            model=coordinator.profile.name,
        )

    @property
    def native_value(self) -> float | int | None:
        """Return the value stored under this sensor's key."""
        return self.coordinator.data.get(self.entity_description.key)


class BraunTemperatureSensor(BraunSensor):
    """Temperature sensor carrying metadata from the latest measurement."""

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
