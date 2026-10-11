"""ThermoScan protocol: Kaz encrypted session, record reading and acknowledgement."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
import os
import struct
from typing import TYPE_CHECKING, Any

from bleak import BleakClient

from ..const import (
    BATTERY_LEVEL_UUID,
    CONF_AUTH_KEY,
    CONF_ENC_KEY,
    FIRMWARE_REVISION_UUID,
    MODEL_NUMBER_UUID,
)
from .kaz_crypto import compute_challenge_response, decrypt_frame, derive_recovery_key, encrypt_frame

if TYPE_CHECKING:
    from ..coordinator import BraunDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

# Advertised without a local name; the name only comes in the scan response.
RECORD_SERVICE_UUID = "aeb23580-80b6-432d-9b5a-57ff6feea94e"
CHALLENGE_REQUEST_UUID = "8de5fe92-2b6e-4f23-acea-ea7aae6b44fe"
CHALLENGE_RESPONSE_UUID = "fd700b4a-845e-4f41-aafa-333378f07462"
CHALLENGE_RECOVERY_UUID = "b97838b9-2649-4c99-bbdc-0acf217300e3"
RECORD_COUNT_UUID = "01766d60-0f08-4366-9778-d5d6c470531b"
RECORD_INDEX_REQUEST_UUID = "220acbcf-3d5d-4720-82f3-88103d804fbb"
RECORD_NOTIFICATION_UUID = "0fc7830b-ce64-4364-8332-00a32f6aa8e2"
FINAL_TEMP_NOTIFICATION_UUID = "fbacb31a-6d77-4a8c-8c2d-f149ea9ff36e"

# Encrypted [command, index] frames written to RECORD_INDEX_REQUEST_UUID
READ_OLDEST_RECORD = b"\x00\x00"
ACK_OLDEST_RECORD = b"\x01\x00"

RECOVERY_MAGIC = bytes.fromhex("018d54d5")
PIN_TIMEOUT = 20.0
SESSION_TIMEOUT = 300
AGE_PROFILES = {1: "0_3_months", 2: "3_36_months", 3: "over_36_months"}


def parse_record(payload: bytes) -> dict[str, Any]:
    """Parse a decrypted ThermoScan record (21 bytes, big-endian).

    Measured on a TS7+ with firmware 1.2.0: [0] index, [4] sequence number,
    [6:10] measurement time (Unix, UTC), [12:16] body temperature (float32, °C),
    [16] low two bits: age profile chosen on the device, [17:21] ambient temperature
    (float32, °C). The other bytes are unknown.
    """
    result: dict[str, Any] = {"raw_hex": payload.hex()}
    if len(payload) < 21:
        return result
    (body,) = struct.unpack(">f", payload[12:16])
    (ambient,) = struct.unpack(">f", payload[17:21])
    return result | {
        "sequence": payload[4],
        "timestamp": datetime.fromtimestamp(int.from_bytes(payload[6:10], "big"), UTC).isoformat(),
        "temperature": round(body, 1),
        "ambient_temperature": round(ambient, 1),
        "age_profile": AGE_PROFILES.get(payload[16] & 0x03),
        "unit": "°C",
    }


async def async_request_pin(client: BleakClient) -> tuple[bytes, bytes]:
    """Ask a device in pairing mode to show its PIN; return the IV and the encrypted keys.

    Raises TimeoutError when the device does not answer.
    """
    keys: asyncio.Queue[bytes] = asyncio.Queue()
    await client.start_notify(CHALLENGE_RECOVERY_UUID, lambda _char, data: keys.put_nowait(bytes(data)))
    # Reading the challenge wakes the crypto engine up.
    await client.read_gatt_char(CHALLENGE_REQUEST_UUID)
    iv = os.urandom(12)
    await client.write_gatt_char(CHALLENGE_RESPONSE_UUID, RECOVERY_MAGIC + iv + b"\x5f", response=True)
    _LOGGER.info("Recovery packet sent, waiting for the device to display its PIN")
    return iv, await asyncio.wait_for(keys.get(), timeout=PIN_TIMEOUT)


def keys_from_pin(pin: str, iv: bytes, encrypted: bytes) -> dict[str, str] | None:
    """Decrypt the pairing keys with the PIN shown on the device; None if it does not match."""
    # Raw digit bytes are the Kaz standard; ASCII is tried for untested models.
    for as_ascii in (False, True):
        try:
            keys = decrypt_frame(encrypted, derive_recovery_key(pin, as_ascii=as_ascii), iv)
        except Exception:
            continue
        if len(keys) >= 32:
            return {CONF_AUTH_KEY: keys[:16].hex(), CONF_ENC_KEY: keys[16:32].hex()}
    return None


class _RecordSync:
    """Encrypted record commands for one authenticated session."""

    def __init__(
        self, client: BleakClient, key: bytes, iv: bytes, records: asyncio.Queue[bytes]
    ) -> None:
        self._client = client
        self._key = key
        self._iv = iv
        self._records = records
        self._counter = 1

    async def pending(self) -> int:
        """Return the number of measurements not yet synced (second byte)."""
        frame = await self._client.read_gatt_char(RECORD_COUNT_UUID)
        return decrypt_frame(frame, self._key, self._iv)[1]

    async def read_oldest(self) -> bytes:
        """Return the decrypted oldest new record."""
        await self._send(READ_OLDEST_RECORD)
        frame = await asyncio.wait_for(self._records.get(), timeout=3.5)
        return decrypt_frame(frame, self._key, self._iv)

    async def ack_oldest(self) -> None:
        """Mark the oldest new record as synced; the next one moves to index 0."""
        await self._send(ACK_OLDEST_RECORD)

    async def _send(self, command: bytes) -> None:
        self._counter += 1
        req = encrypt_frame(command, self._key, self._iv, self._counter)
        await self._client.write_gatt_char(RECORD_INDEX_REQUEST_UUID, req, response=True)


async def async_run_session(
    coordinator: BraunDataUpdateCoordinator, client: BleakClient, disconnected: asyncio.Event
) -> None:
    """Sync pending records, then sync again on every final temperature until disconnected."""
    # True: a measurement was just taken. False: the device disconnected.
    wakeups: asyncio.Queue[bool] = asyncio.Queue()
    records: asyncio.Queue[bytes] = asyncio.Queue()
    watcher = asyncio.create_task(disconnected.wait())
    watcher.add_done_callback(lambda _task: wakeups.put_nowait(False))
    try:
        await client.start_notify(
            RECORD_NOTIFICATION_UUID, lambda _char, data: records.put_nowait(bytes(data))
        )
        await client.start_notify(
            FINAL_TEMP_NOTIFICATION_UUID, lambda _char, _data: wakeups.put_nowait(True)
        )
        session_iv = os.urandom(12)
        auth_key = bytes.fromhex(coordinator.entry.data[CONF_AUTH_KEY])
        challenge = await client.read_gatt_char(CHALLENGE_REQUEST_UUID)
        resp = compute_challenge_response(challenge, auth_key, session_iv)
        await client.write_gatt_char(CHALLENGE_RESPONSE_UUID, resp, response=True)
        _LOGGER.debug("Authenticated with %s", coordinator.address)

        coordinator.data["battery"] = (await client.read_gatt_char(BATTERY_LEVEL_UUID))[0]
        coordinator.data["model_number"] = (await client.read_gatt_char(MODEL_NUMBER_UUID)).decode()
        coordinator.data["firmware"] = (await client.read_gatt_char(FIRMWARE_REVISION_UUID)).decode()

        enc_key = bytes.fromhex(coordinator.entry.data[CONF_ENC_KEY])
        sync = _RecordSync(client, enc_key, session_iv, records)
        await _async_sync_pending(coordinator, sync)
        # The device turns itself off about a minute after the last measurement.
        while True:
            try:
                measured = await asyncio.wait_for(wakeups.get(), timeout=SESSION_TIMEOUT)
            except TimeoutError:
                _LOGGER.debug("Session with %s timed out", coordinator.address)
                break
            if not measured:
                break
            await _async_sync_pending(coordinator, sync)
    finally:
        watcher.cancel()


async def _async_sync_pending(coordinator: BraunDataUpdateCoordinator, sync: _RecordSync) -> None:
    """Read, hand over and acknowledge every measurement not yet synced."""
    pending = await sync.pending()
    _LOGGER.debug("Device has %d new records", pending)
    for _ in range(pending):
        await coordinator.async_add_record(parse_record(await sync.read_oldest()))
        await sync.ack_oldest()
    coordinator.async_synced()
