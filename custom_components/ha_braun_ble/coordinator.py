"""DataUpdateCoordinator for Braun BLE devices."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import os
from typing import Any

from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
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
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    BATTERY_LEVEL_UUID,
    CHALLENGE_REQUEST_UUID,
    CHALLENGE_RESPONSE_UUID,
    CONF_AUTH_KEY,
    CONF_ENC_KEY,
    CONF_MODEL,
    EVENT_BRAUN_MEASUREMENT,
    FINAL_TEMP_NOTIFICATION_UUID,
    RECORD_COUNT_UUID,
    RECORD_INDEX_REQUEST_UUID,
    RECORD_NOTIFICATION_UUID,
)
from .crypto import (
    compute_challenge_response,
    decrypt_frame,
    encrypt_frame,
)
from .models import BraunModelProfile, SUPPORTED_MODELS, get_model_profile_by_name

_LOGGER = logging.getLogger(__name__)


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
        self._last_synced_record_index: int = entry.data.get("last_synced_index", -1)

        # In-memory sensor state cache
        self.data: dict[str, Any] = {
            "temperature": None,
            "age_group": None,
            "fever_status": None,
            "battery": None,
            "record_count": None,
            "last_synced": None,
            "latest_record": {},
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
        """Connect to thermometer, perform authenticated handshake and download new records."""
        if self._sync_lock.locked():
            _LOGGER.debug("Sync already in progress for %s, skipping", self.address)
            return

        async with self._sync_lock:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=True
            )
            if not ble_device:
                _LOGGER.debug("Device %s not available in BLE cache", self.address)
                return

            _LOGGER.info("Connecting to Braun device %s...", self.address)
            try:
                client = await establish_connection(
                    BleakClient,
                    ble_device,
                    self.entry.title,
                    max_attempts=2,
                )
            except Exception as err:
                _LOGGER.debug("Could not connect to %s (device likely asleep): %s", self.address, err)
                return

            try:
                await self._async_perform_sync(client)
            except Exception as err:
                _LOGGER.warning("Sync failed with device %s: %s", self.address, err, exc_info=True)
            finally:
                try:
                    await client.disconnect()
                except Exception:
                    pass

    async def _async_perform_sync(self, client: BleakClient) -> None:
        """Execute the authenticated handshake and read records."""
        services = client.services
        chars = {c.uuid.lower(): c for s in services for c in s.characteristics}

        # Validate mandatory characteristics
        if CHALLENGE_REQUEST_UUID.lower() not in chars or CHALLENGE_RESPONSE_UUID.lower() not in chars:
            raise UpdateFailed("Device does not expose expected Kaz/Braun auth characteristics")

        # Set up notification queue for incoming records
        records_queue: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()

        def _notification_handler(char: BleakGATTCharacteristic, data: bytearray) -> None:
            records_queue.put_nowait((char.uuid.lower(), bytes(data)))

        # Subscribe to record notification characteristics
        for uuid_str in (RECORD_NOTIFICATION_UUID, FINAL_TEMP_NOTIFICATION_UUID):
            if uuid_str.lower() in chars:
                try:
                    await client.start_notify(uuid_str, _notification_handler)
                except Exception as err:
                    _LOGGER.debug("Could not subscribe to %s: %s", uuid_str, err)

        # 1. Challenge / Response authentication
        challenge = await client.read_gatt_char(CHALLENGE_REQUEST_UUID)
        session_iv = os.urandom(12)
        resp = compute_challenge_response(challenge, self.auth_key, session_iv)
        await client.write_gatt_char(CHALLENGE_RESPONSE_UUID, resp, response=True)
        _LOGGER.debug("Authenticated successfully with %s", self.address)

        # 2. Read Battery Level (0x2A19) if present
        if BATTERY_LEVEL_UUID.lower() in chars:
            try:
                bat_raw = await client.read_gatt_char(BATTERY_LEVEL_UUID)
                if bat_raw:
                    self.data["battery"] = int(bat_raw[0])
            except Exception as err:
                _LOGGER.debug("Could not read battery level: %s", err)

        # 3. Read Stored Record Count
        num_records = 0
        if RECORD_COUNT_UUID.lower() in chars:
            enc_count = await client.read_gatt_char(RECORD_COUNT_UUID)
            if enc_count:
                dec_count = decrypt_frame(enc_count, self.enc_key, session_iv)
                if len(dec_count) >= 2:
                    num_records = int.from_bytes(dec_count[:2], "little")
                    self.data["record_count"] = num_records
                    _LOGGER.debug("Device has %d stored records", num_records)

        # 4. Read new records
        latest_record_data: dict[str, Any] = {}
        counter = 1

        if RECORD_INDEX_REQUEST_UUID.lower() in chars and num_records > 0:
            # Query the newest records
            start_index = max(0, self._last_synced_record_index + 1)
            # If records were cleared or reset, sync last few records
            if start_index >= num_records:
                start_index = max(0, num_records - 1)

            for idx in range(start_index, num_records):
                counter += 1
                req = encrypt_frame(idx.to_bytes(2, "little"), self.enc_key, session_iv, counter)
                await client.write_gatt_char(RECORD_INDEX_REQUEST_UUID, req, response=True)

                try:
                    _uuid, frame = await asyncio.wait_for(records_queue.get(), timeout=3.5)
                    plain = decrypt_frame(frame, self.enc_key, session_iv)
                    
                    parsed = {}
                    if self.profile.record_parser:
                        parsed = self.profile.record_parser(plain)
                    else:
                        parsed = {"raw_hex": plain.hex()}

                    latest_record_data = parsed
                    self._last_synced_record_index = idx

                    # Dispatch Home Assistant Event for each measurement
                    self._async_dispatch_measurement_event(parsed)

                except asyncio.TimeoutError:
                    _LOGGER.debug("Timeout waiting for record %d", idx)
                    break
                except Exception as err:
                    _LOGGER.warning("Error decrypting record %d: %s", idx, err)

        # Update cache data if new record found
        if latest_record_data:
            if "temperature" in latest_record_data:
                self.data["temperature"] = latest_record_data["temperature"]
            if "fever_status" in latest_record_data:
                self.data["fever_status"] = latest_record_data["fever_status"]
            if "age_group" in latest_record_data:
                self.data["age_group"] = latest_record_data["age_group"]
            self.data["latest_record"] = latest_record_data

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
