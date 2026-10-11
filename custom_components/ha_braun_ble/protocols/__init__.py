"""Device protocols: how each Braun model is reached over Bluetooth and hands over its records."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from bleak import BleakClient

from ..const import FIRMWARE_REVISION_UUID, MODEL_NUMBER_UUID

if TYPE_CHECKING:
    from ..coordinator import BraunDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_read_identity(coordinator: BraunDataUpdateCoordinator, client: BleakClient) -> None:
    """Read the standard model number and firmware revision strings."""
    for key, uuid in (("model_number", MODEL_NUMBER_UUID), ("firmware", FIRMWARE_REVISION_UUID)):
        raw = bytes(await client.read_gatt_char(uuid))
        _LOGGER.debug("%s %s raw: %s", coordinator.address, key, raw.hex())
        coordinator.data[key] = raw.decode(errors="replace")
