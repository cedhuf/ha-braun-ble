"""Sensor platform for Braun Health BLE integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SUBENTRY_PERSON
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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Braun BLE sensors based on a config entry."""
    coordinator: BraunDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    persons = entry.get_subentries_of_type(SUBENTRY_PERSON)

    expected = {f"{coordinator.address}_{d.key}" for d in (TEMPERATURE, BATTERY)}
    expected |= {f"{person.subentry_id}_temperature" for person in persons}
    ent_reg = er.async_get(hass)
    for stale in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if stale.domain == "sensor" and stale.unique_id not in expected:
            ent_reg.async_remove(stale.entity_id)

    async_add_entities(
        [
            BraunTemperatureSensor(coordinator, TEMPERATURE),
            BraunSensor(coordinator, BATTERY),
        ]
    )
    for person in persons:
        async_add_entities(
            [BraunPersonTemperatureSensor(coordinator, person)],
            config_subentry_id=person.subentry_id,
        )


def _device_info(coordinator: BraunDataUpdateCoordinator) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.address)},
        name=coordinator.entry.title,
        manufacturer="Braun (Kaz / Helen of Troy)",
        model=coordinator.profile.name,
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
        self._attr_device_info = _device_info(coordinator)

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
            "measured_at": rec.get("timestamp"),
            "ambient_temperature": rec.get("ambient_temperature"),
            "sequence": rec.get("sequence"),
            "last_synced": self.coordinator.data.get("last_synced"),
            "raw_hex": rec.get("raw_hex"),
        }


class BraunPersonTemperatureSensor(CoordinatorEntity[BraunDataUpdateCoordinator], RestoreSensor):
    """Latest temperature attributed to one person, kept across restarts."""

    _attr_has_entity_name = True
    _attr_translation_key = "person_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: BraunDataUpdateCoordinator, person: ConfigSubentry) -> None:
        """Initialize the person's temperature sensor."""
        super().__init__(coordinator)
        self._person_id = person.subentry_id
        self._attr_unique_id = f"{person.subentry_id}_temperature"
        # Subentry entities must sit on a device of their own subentry.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, person.subentry_id)},
            name=person.title,
            entry_type=DeviceEntryType.SERVICE,
            via_device=(DOMAIN, coordinator.address),
        )
        self._attr_extra_state_attributes = {"measured_at": None}

    async def async_added_to_hass(self) -> None:
        """Restore the last attributed measurement."""
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) and (
            state := await self.async_get_last_state()
        ):
            self._attr_native_value = data.native_value
            self._attr_extra_state_attributes = {"measured_at": state.attributes.get("measured_at")}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Take the person's record if it is newer than the one shown."""
        record = self.coordinator.data["persons"].get(self._person_id)
        shown = self._attr_extra_state_attributes["measured_at"]
        if record and (shown is None or record["timestamp"] >= shown):
            self._attr_native_value = record["temperature"]
            self._attr_extra_state_attributes = {"measured_at": record["timestamp"]}
        super()._handle_coordinator_update()
