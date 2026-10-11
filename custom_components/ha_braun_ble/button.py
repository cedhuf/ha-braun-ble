"""Buttons to attribute or drop the oldest pending measurement."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SUBENTRY_PERSON
from .coordinator import BraunDataUpdateCoordinator
from .sensor import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one button per person, plus one to drop the measurement."""
    coordinator: BraunDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [BraunAssignButton(coordinator, None)]
        + [
            BraunAssignButton(coordinator, person)
            for person in entry.get_subentries_of_type(SUBENTRY_PERSON)
        ]
    )


class BraunAssignButton(CoordinatorEntity[BraunDataUpdateCoordinator], ButtonEntity):
    """Attribute the oldest pending measurement to a person, or drop it."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: BraunDataUpdateCoordinator, person: ConfigSubentry | None
    ) -> None:
        """Initialize the button; no person means drop the measurement."""
        super().__init__(coordinator)
        # Kept on the thermometer device, outside the person subentry, so the
        # buttons sit next to the pending measurement.
        self._attr_device_info = device_info(coordinator)
        if person is None:
            self._person_id = None
            self._attr_translation_key = "ignore"
            self._attr_unique_id = f"{coordinator.address}_ignore"
        else:
            self._person_id = person.subentry_id
            self._attr_translation_key = "assign"
            self._attr_translation_placeholders = {"person": person.title}
            self._attr_unique_id = f"{person.subentry_id}_assign"

    @property
    def available(self) -> bool:
        """Only usable while a measurement is waiting."""
        return super().available and bool(self.coordinator.pending)

    async def async_press(self) -> None:
        """Attribute or drop the oldest pending measurement."""
        await self.coordinator.async_assign(None, self._person_id)
