"""Sensor platform for Braun Health BLE integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SUBENTRY_PERSON
from .coordinator import BraunDataUpdateCoordinator
from .kinds import BraunSensorDescription
from .messages import text



async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Braun BLE sensors based on a config entry."""
    coordinator: BraunDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    persons = entry.get_subentries_of_type(SUBENTRY_PERSON)

    kind = coordinator.profile.kind
    async_add_entities(
        [BraunSensor(coordinator, d) for d in (*kind.device_sensors, *coordinator.profile.common_sensors)]
        + [BraunPendingSensor(coordinator)]
    )
    for person in persons:
        async_add_entities(
            [BraunPersonSensor(coordinator, person, d) for d in kind.person_sensors],
            config_subentry_id=person.subentry_id,
        )


class BraunSensor(CoordinatorEntity[BraunDataUpdateCoordinator], RestoreSensor):
    """Sensor reading one key of the coordinator data."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BraunDataUpdateCoordinator, description: SensorEntityDescription
    ) -> None:
        """Initialize Braun sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.address}_{description.key}"
        self._attr_device_info = coordinator.device_info

    async def async_added_to_hass(self) -> None:
        """Show the last known value until the device next connects."""
        await super().async_added_to_hass()
        key = self.entity_description.key
        if self.coordinator.data.get(key) is None and (last := await self.async_get_last_sensor_data()):
            self.coordinator.data[key] = last.native_value

    @property
    def native_value(self) -> float | int | str | None:
        """Return the value stored under this sensor's key."""
        return self.coordinator.data.get(self.entity_description.key)


    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the latest record's details, for sensors that ask for them."""
        description = self.entity_description
        if not (isinstance(description, BraunSensorDescription) and description.record_attributes):
            return None
        rec = self.coordinator.data.get("latest_record") or {}
        return {
            "measured_at": rec.get("timestamp"),
            **{key: rec.get(key) for key in self.coordinator.profile.kind.attributes},
            "sequence": rec.get("sequence"),
            "last_synced": self.coordinator.data.get("last_synced"),
            "raw_hex": rec.get("raw_hex"),
        }


class BraunPersonSensor(CoordinatorEntity[BraunDataUpdateCoordinator], RestoreSensor):
    """Latest value attributed to one person, kept across restarts."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: BraunDataUpdateCoordinator,
        person: ConfigSubentry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the person's sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._person_id = person.subentry_id
        self._attr_unique_id = f"{person.subentry_id}_{description.key}"
        # Subentry entities must sit on a device of their own subentry.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, person.subentry_id)},
            name=person.title,
            entry_type=DeviceEntryType.SERVICE,
            via_device_id=coordinator.device_id,
        )
        self._attr_extra_state_attributes = {"measured_at": None}

    async def async_added_to_hass(self) -> None:
        """Restore the last attributed measurement."""
        await super().async_added_to_hass()
        if (data := await self.async_get_last_sensor_data()) and (
            state := await self.async_get_last_state()
        ):
            self._attr_native_value = data.native_value
            self._attr_extra_state_attributes = {
                key: state.attributes.get(key) for key in ("measured_at", *self._kind_attributes)
            }

    @property
    def _kind_attributes(self) -> tuple[str, ...]:
        return self.coordinator.profile.kind.attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        """Take the person's record if it is newer than the one shown."""
        record = self.coordinator.data["persons"].get(self._person_id)
        shown = self._attr_extra_state_attributes["measured_at"]
        if record and (shown is None or record["timestamp"] >= shown):
            self._attr_native_value = record[self.entity_description.key]
            self._attr_extra_state_attributes = {
                "measured_at": record["timestamp"],
                **{key: record.get(key) for key in self._kind_attributes},
            }
        super()._handle_coordinator_update()


class BraunPendingSensor(CoordinatorEntity[BraunDataUpdateCoordinator], SensorEntity):
    """Oldest measurement still waiting to be attributed, as text with its time."""

    _attr_has_entity_name = True
    _attr_translation_key = "pending"

    def __init__(self, coordinator: BraunDataUpdateCoordinator) -> None:
        """Initialize the pending measurement sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_pending"
        self._attr_device_info = coordinator.device_info

    @property
    def native_value(self) -> str:
        """Return the oldest pending measurement and when it was taken."""
        if not self.coordinator.pending:
            return text(self.hass, "no_pending")
        return text(self.hass, "pending_value", self.coordinator.pending[0])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the raw values and how many measurements are waiting."""
        oldest = self.coordinator.pending[0] if self.coordinator.pending else {}
        kind = self.coordinator.profile.kind
        return {
            **{key: oldest.get(key) for key in kind.value_fields},
            "measured_at": oldest.get("timestamp"),
            **{key: oldest.get(key) for key in kind.attributes},
            "waiting": len(self.coordinator.pending),
        }
