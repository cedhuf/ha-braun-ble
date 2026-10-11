"""The Braun Health BLE component."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import DOMAIN, SUBENTRY_PERSON
from .coordinator import BraunDataUpdateCoordinator
from .kinds import COMMON_SENSORS

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the sync service once for all devices."""
    hass.data.setdefault(DOMAIN, {})

    async def async_handle_sync_service(call: ServiceCall) -> None:
        """Sync every configured device."""
        for coordinator in list(hass.data[DOMAIN].values()):
            _LOGGER.info("Manual sync triggered for %s", coordinator.entry.title)
            await coordinator.async_sync_device()

    hass.services.async_register(DOMAIN, "sync", async_handle_sync_service)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Braun BLE from a config entry."""
    coordinator = BraunDataUpdateCoordinator(hass, entry)
    await coordinator.async_setup()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    _async_remove_stale_entities(hass, entry, coordinator)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    return True


def _async_remove_stale_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: BraunDataUpdateCoordinator
) -> None:
    """Drop entities from earlier versions or from removed people."""
    kind = coordinator.profile.kind
    device_keys = [d.key for d in kind.device_sensors] + [d.key for d in COMMON_SENSORS]
    expected = {f"{coordinator.address}_{key}" for key in (*device_keys, "pending", "ignore")}
    for person in entry.get_subentries_of_type(SUBENTRY_PERSON):
        expected |= {f"{person.subentry_id}_{d.key}" for d in kind.person_sensors}
        expected.add(f"{person.subentry_id}_assign")
    ent_reg = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if entity.unique_id not in expected:
            ent_reg.async_remove(entity.entity_id)


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload so added or removed people get their sensors."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: BraunDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_unload()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
