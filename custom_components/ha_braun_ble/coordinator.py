"""DataUpdateCoordinator for Braun BLE devices."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import os
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ACK_OLDEST_RECORD,
    BATTERY_LEVEL_UUID,
    CHALLENGE_REQUEST_UUID,
    CHALLENGE_RESPONSE_UUID,
    CONF_AUTH_KEY,
    CONF_ENC_KEY,
    CONF_MODEL,
    EVENT_BRAUN_MEASUREMENT,
    FINAL_TEMP_NOTIFICATION_UUID,
    READ_OLDEST_RECORD,
    RECORD_COUNT_UUID,
    RECORD_INDEX_REQUEST_UUID,
    RECORD_NOTIFICATION_UUID,
    SUBENTRY_PERSON,
)
from .crypto import (
    compute_challenge_response,
    decrypt_frame,
    encrypt_frame,
)
from .models import BraunModelProfile, SUPPORTED_MODELS, get_model_profile_by_name

_LOGGER = logging.getLogger(__name__)


SESSION_TIMEOUT = 300


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


class BraunDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator managing Braun BLE connection, crypto handshake and record syncing."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Braun BLE ({entry.title})",
        )
        self.entry = entry
        self.address: str = entry.unique_id or entry.data["address"]
        self.auth_key: bytes = bytes.fromhex(entry.data[CONF_AUTH_KEY])
        self.enc_key: bytes = bytes.fromhex(entry.data[CONF_ENC_KEY])

        model_id = entry.data.get(CONF_MODEL, "IRT6575")
        self.profile: BraunModelProfile = SUPPORTED_MODELS.get(
            model_id, get_model_profile_by_name(entry.title)
        )

        self._unsubscribe_ble: CALLBACK_TYPE | None = None
        self._sync_lock = asyncio.Lock()

        # In-memory sensor state cache
        self.data: dict[str, Any] = {
            "temperature": None,
            "battery": None,
            "last_synced": None,
            "latest_record": {},
            # Latest record per person subentry id
            "persons": {},
        }

    async def async_setup(self) -> None:
        """Register passive Bluetooth listener to trigger sync when device wakes up."""
        _LOGGER.debug("Setting up Bluetooth listener for %s (%s)", self.profile.name, self.address)
        self._unsubscribe_ble = bluetooth.async_register_callback(
            self.hass,
            self._async_handle_bluetooth_advertisement,
            BluetoothCallbackMatcher(address=self.address, connectable=True),
            BluetoothScanningMode.PASSIVE,
        )

    @callback
    def _async_handle_bluetooth_advertisement(
        self,
        service_info: BluetoothServiceInfoBleak,
        change: BluetoothChange,
    ) -> None:
        """Handle incoming advertisement indicating device has woken up."""
        _LOGGER.debug(
            "Device %s advertised (rssi: %s). Scheduling sync...",
            self.address,
            service_info.rssi,
        )
        # Schedule background sync if not already syncing
        if not self._sync_lock.locked():
            self.hass.async_create_task(self.async_sync_device())

    async def _async_update_data(self) -> dict[str, Any]:
        """Coordinator update method. Sync device if reachable."""
        await self.async_sync_device()
        return self.data

    async def async_sync_device(self) -> None:
        """Stay connected while the thermometer is on, syncing each new measurement."""
        if self._sync_lock.locked():
            _LOGGER.debug("Session already open with %s, skipping", self.address)
            return

        async with self._sync_lock:
            try:
                await self._async_run_session()
            finally:
                # The thermometer sends the same advertisement at every power-on, which
                # Home Assistant drops as unchanged unless the history is cleared.
                bluetooth.async_clear_advertisement_history(self.hass, self.address)

    async def _async_run_session(self) -> None:
        """Connect, sync pending records, then sync again on every final temperature."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if not ble_device:
            _LOGGER.debug("Device %s not available in BLE cache", self.address)
            return

        # True: a measurement was just taken. False: the device disconnected.
        wakeups: asyncio.Queue[bool] = asyncio.Queue()
        records: asyncio.Queue[bytes] = asyncio.Queue()

        _LOGGER.info("Connecting to Braun device %s...", self.address)
        try:
            client = await establish_connection(
                BleakClient,
                ble_device,
                self.entry.title,
                disconnected_callback=lambda _client: wakeups.put_nowait(False),
                max_attempts=2,
            )
        except Exception as err:
            _LOGGER.debug("Could not connect to %s (device likely asleep): %s", self.address, err)
            return

        try:
            await client.start_notify(
                RECORD_NOTIFICATION_UUID, lambda _char, data: records.put_nowait(bytes(data))
            )
            await client.start_notify(
                FINAL_TEMP_NOTIFICATION_UUID, lambda _char, _data: wakeups.put_nowait(True)
            )
            session_iv = os.urandom(12)
            challenge = await client.read_gatt_char(CHALLENGE_REQUEST_UUID)
            resp = compute_challenge_response(challenge, self.auth_key, session_iv)
            await client.write_gatt_char(CHALLENGE_RESPONSE_UUID, resp, response=True)
            _LOGGER.debug("Authenticated with %s", self.address)

            battery = await client.read_gatt_char(BATTERY_LEVEL_UUID)
            self.data["battery"] = battery[0]

            sync = _RecordSync(client, self.enc_key, session_iv, records)
            await self._async_sync_pending(sync)
            # The device turns itself off about a minute after the last measurement.
            while True:
                try:
                    measured = await asyncio.wait_for(wakeups.get(), timeout=SESSION_TIMEOUT)
                except TimeoutError:
                    _LOGGER.debug("Session with %s timed out", self.address)
                    break
                if not measured:
                    break
                await self._async_sync_pending(sync)
        except Exception as err:
            if client.is_connected:
                _LOGGER.warning("Sync failed with device %s: %s", self.address, err, exc_info=True)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        _LOGGER.debug("Session with %s closed", self.address)

    async def _async_sync_pending(self, sync: _RecordSync) -> None:
        """Read, publish and acknowledge every measurement not yet synced."""
        pending = await sync.pending()
        _LOGGER.debug("Device has %d new records", pending)
        for _ in range(pending):
            record = self.profile.record_parser(await sync.read_oldest())
            persons = self.entry.get_subentries_of_type(SUBENTRY_PERSON)
            if len(persons) == 1 and "temperature" in record:
                record["person"] = persons[0].title
                self.data["persons"][persons[0].subentry_id] = record
            self._async_dispatch_measurement_event(record)
            self.data["latest_record"] = record
            if "temperature" in record:
                self.data["temperature"] = record["temperature"]
            await sync.ack_oldest()

        self.data["last_synced"] = datetime.now().isoformat()
        self.async_set_updated_data(self.data)

    def _async_dispatch_measurement_event(self, record: dict[str, Any]) -> None:
        """Fire event on Home Assistant event bus for automations / person assignment."""
        event_data = {
            "entry_id": self.entry.entry_id,
            "device_address": self.address,
            "device_name": self.entry.title,
            "model": self.profile.name,
            **record,
        }
        _LOGGER.info("Firing %s event: %s", EVENT_BRAUN_MEASUREMENT, event_data)
        self.hass.bus.async_fire(EVENT_BRAUN_MEASUREMENT, event_data)

    async def async_unload(self) -> None:
        """Unload coordinator and clean up listeners."""
        if self._unsubscribe_ble:
            self._unsubscribe_ble()
            self._unsubscribe_ble = None
