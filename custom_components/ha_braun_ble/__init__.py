"""The Braun Health BLE component."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import BraunDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

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

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator: BraunDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_unload()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
