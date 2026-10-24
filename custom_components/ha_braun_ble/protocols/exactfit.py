"""ExactFit protocol: finished measurements notified in the standard blood pressure layout."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, tzinfo
import logging
from typing import TYPE_CHECKING, Any

from bleak import BleakClient

from . import async_read_identity

if TYPE_CHECKING:
    from ..coordinator import BraunDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

MEASUREMENT_SERVICE_UUID = "56484aae-a8eb-4a97-ac19-a8ea6373e05a"
MEASUREMENT_UUID = "2db34480-bce5-4bb7-9f56-55bd202317c5"
# User ids sent by the device, in order.
USERS = ("A", "B")
KPA_TO_MMHG = 7.50062
SESSION_TIMEOUT = 300


def _sfloat(raw: bytes) -> float:
    """Decode an IEEE-11073 16-bit SFLOAT."""
    value = int.from_bytes(raw, "little")
    mantissa = value & 0x0FFF
    exponent = value >> 12
    if mantissa >= 0x0800:
        mantissa -= 0x1000
    if exponent >= 0x08:
        exponent -= 0x10
    return mantissa * 10**exponent


def parse_record(payload: bytes, local_tz: tzinfo) -> dict[str, Any]:
    """Parse a Blood Pressure Measurement (0x2A35 layout); the device stamps local time."""
    result: dict[str, Any] = {"raw_hex": payload.hex()}
    if len(payload) < 7:
        return result
    flags = payload[0]
    scale = KPA_TO_MMHG if flags & 0x01 else 1
    result |= {
        "systolic": round(_sfloat(payload[1:3]) * scale),
        "diastolic": round(_sfloat(payload[3:5]) * scale),
        "mean_arterial_pressure": round(_sfloat(payload[5:7]) * scale),
        "unit": "mmHg",
    }
    offset = 7
    if flags & 0x02:
        year = int.from_bytes(payload[offset : offset + 2], "little")
        month, day, hour, minute, second = payload[offset + 2 : offset + 7]
        local = datetime(year, month, day, hour, minute, second, tzinfo=local_tz)
        result["timestamp"] = local.astimezone(UTC).isoformat()
        offset += 7
    else:
        result["timestamp"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    if flags & 0x04:
        result["pulse"] = round(_sfloat(payload[offset : offset + 2]))
        offset += 2
    if flags & 0x08:
        user = payload[offset]
        result["user"] = USERS[user] if user < len(USERS) else str(user)
        offset += 1
    if flags & 0x10:
        status = int.from_bytes(payload[offset : offset + 2], "little")
        result |= {
            "body_movement": bool(status & 0x01),
            "cuff_too_loose": bool(status & 0x02),
            "irregular_pulse": bool(status & 0x04),
        }
    return result


async def async_run_session(
    coordinator: BraunDataUpdateCoordinator, client: BleakClient, disconnected: asyncio.Event
) -> None:
    """Hand over every measurement notified until the monitor switches itself off."""
    # A payload per measurement; None once the device disconnected.
    payloads: asyncio.Queue[bytes | None] = asyncio.Queue()
    watcher = asyncio.create_task(disconnected.wait())
    watcher.add_done_callback(lambda _task: payloads.put_nowait(None))
    try:
        await client.start_notify(MEASUREMENT_UUID, lambda _char, data: payloads.put_nowait(bytes(data)))
        await async_read_identity(coordinator, client)
        await coordinator.async_synced()
        while True:
            try:
                payload = await asyncio.wait_for(payloads.get(), timeout=SESSION_TIMEOUT)
            except TimeoutError:
                _LOGGER.debug("Session with %s timed out", coordinator.address)
                break
            if payload is None:
                break
            await coordinator.async_add_record(parse_record(payload, coordinator.time_zone))
            await coordinator.async_synced()
    finally:
        watcher.cancel()
