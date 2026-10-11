"""DataUpdateCoordinator for Braun BLE devices."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
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
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import UnitOfTemperature
from homeassistant.components import persistent_notification
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    ACK_OLDEST_RECORD,
    BATTERY_LEVEL_UUID,
    CHALLENGE_REQUEST_UUID,
    CHALLENGE_RESPONSE_UUID,
    CONF_AUTH_KEY,
    CONF_DEFAULT_PERSON,
    CONF_ENC_KEY,
    CONF_MODEL,
    CONF_NOTIFY,
    DOMAIN,
    EVENT_BRAUN_ATTRIBUTION,
    EVENT_BRAUN_IGNORED,
    EVENT_BRAUN_MEASUREMENT,
    FINAL_TEMP_NOTIFICATION_UUID,
    FIRMWARE_REVISION_UUID,
    MODEL_NUMBER_UUID,
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
from .messages import text
from .models import BraunModelProfile, SUPPORTED_MODELS, get_model_profile_by_name

_LOGGER = logging.getLogger(__name__)


SESSION_TIMEOUT = 300


def _record_id(record: dict[str, Any]) -> str:
    """Identify a measurement by its time and the device sequence number."""
    return f"{int(datetime.fromisoformat(record['timestamp']).timestamp())}_{record['sequence']}"


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
        self._unsubscribe_actions: CALLBACK_TYPE = lambda: None
        self._sync_lock = asyncio.Lock()
        self._store: Store[list[dict[str, Any]]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        # Measurements waiting to be attributed, oldest first
        self.pending: list[dict[str, Any]] = []

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
        """Load pending measurements and listen for the device waking up."""
        self.pending = await self._store.async_load() or []
        for record in self.pending:
            record.setdefault("id", _record_id(record))
        self._async_update_pending_notification()
        self._unsubscribe_actions = self.hass.bus.async_listen(
            "mobile_app_notification_action", self._async_handle_notification_action
        )
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
            self.data["model_number"] = (await client.read_gatt_char(MODEL_NUMBER_UUID)).decode()
            self.data["firmware"] = (await client.read_gatt_char(FIRMWARE_REVISION_UUID)).decode()

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
            if "temperature" in record:
                persons = self.entry.get_subentries_of_type(SUBENTRY_PERSON)
                default = self.entry.subentries.get(self.entry.options.get(CONF_DEFAULT_PERSON) or "")
                if default:
                    await self._async_attribute(record, default)
                elif persons:
                    record["id"] = _record_id(record)
                    self.pending.append(record)
                    await self._store.async_save(self.pending)
                    self._async_update_pending_notification()
                    await self._async_notify_phones(record, persons)
            self._async_dispatch_measurement_event(record)
            self.data["latest_record"] = record
            if "temperature" in record:
                self.data["temperature"] = record["temperature"]
                self.data["ambient_temperature"] = record["ambient_temperature"]
            await sync.ack_oldest()

        self.data["last_synced"] = datetime.now().isoformat()
        self.async_set_updated_data(self.data)

    async def async_assign(self, record_id: str | None, subentry_id: str | None) -> None:
        """Attribute a pending measurement (the oldest when record_id is None) or drop it.

        A subentry_id of None drops the measurement.
        """
        record = next((r for r in self.pending if record_id in (None, r["id"])), None)
        person = self.entry.subentries.get(subentry_id) if subentry_id else None
        if record is None or (subentry_id and person is None):
            return
        self.pending.remove(record)
        await self._store.async_save(self.pending)
        if person is not None:
            await self._async_attribute(record, person)
        else:
            self._async_fire(EVENT_BRAUN_IGNORED, self.address, record)
        self._async_update_pending_notification()
        await self._async_clear_phone_notification(record)
        self.async_update_listeners()

    async def _async_notify_phones(self, record: dict[str, Any], persons: list[ConfigSubentry]) -> None:
        """Ask on each chosen phone who the measurement was for."""
        targets = [*persons, None]
        actions = [
            {
                "action": f"{DOMAIN}|{self.entry.entry_id}|{record['id']}|{p.subentry_id if p else ''}",
                "title": p.title if p else text(self.hass, "ignore"),
            }
            for p in targets
        ]
        await self._async_send_to_phones(
            {
                "title": self.entry.title,
                "message": text(self.hass, "notify_message", record),
                "data": {"tag": record["id"], "actions": actions},
            }
        )

    async def _async_clear_phone_notification(self, record: dict[str, Any]) -> None:
        await self._async_send_to_phones({"message": "clear_notification", "data": {"tag": record["id"]}})

    async def _async_send_to_phones(self, payload: dict[str, Any]) -> None:
        """Notify each chosen phone; a phone removed since must not break the sync."""
        for service in self.entry.options.get(CONF_NOTIFY, []):
            try:
                await self.hass.services.async_call("notify", service, payload)
            except Exception as err:
                _LOGGER.warning("Could not notify %s: %s", service, err)

    async def _async_handle_notification_action(self, event: Event) -> None:
        """Apply a person or ignore button tapped on a phone."""
        parts = event.data.get("action", "").split("|")
        if len(parts) == 4 and parts[0] == DOMAIN and parts[1] == self.entry.entry_id:
            await self.async_assign(parts[2], parts[3] or None)

    @callback
    def _async_update_pending_notification(self) -> None:
        """Keep one Home Assistant notification listing what waits to be attributed."""
        notification_id = f"{DOMAIN}_{self.entry.entry_id}_pending"
        if not self.pending:
            persistent_notification.async_dismiss(self.hass, notification_id)
            return
        device = dr.async_get(self.hass).async_get_device(identifiers={(DOMAIN, self.address)})
        lines = [text(self.hass, "pending_line", record) for record in self.pending]
        if device:
            lines += ["", text(self.hass, "pending_link", device=self.entry.title, device_id=device.id)]
        persistent_notification.async_create(
            self.hass,
            "\n".join(lines),
            title=text(self.hass, "pending_title"),
            notification_id=notification_id,
        )

    async def _async_attribute(self, record: dict[str, Any], person: ConfigSubentry) -> None:
        """Give a measurement to a person and add it to their hourly statistics."""
        record["person"] = person.title
        self.data["persons"][person.subentry_id] = record
        self._async_fire(EVENT_BRAUN_ATTRIBUTION, person.subentry_id, record)

        # Statistics carry the real measurement time, unlike state history.
        statistic_id = f"{DOMAIN}:{person.subentry_id.lower()}_temperature"
        value = record["temperature"]
        hour = datetime.fromisoformat(record["timestamp"]).replace(minute=0, second=0, microsecond=0)
        existing = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            hour,
            hour + timedelta(hours=1),
            {statistic_id},
            "hour",
            None,
            {"mean", "min", "max"},
        )
        low = high = mean = value
        if rows := existing.get(statistic_id):
            low, high = min(rows[0]["min"], value), max(rows[0]["max"], value)
            # ponytail: mean of the stored mean and the new value, exact only for two per hour
            mean = (rows[0]["mean"] + value) / 2
        async_add_external_statistics(
            self.hass,
            StatisticMetaData(
                mean_type=StatisticMeanType.ARITHMETIC,
                has_sum=False,
                name=f"{person.title} {self.entry.title}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_class=TemperatureConverter.UNIT_CLASS,
                unit_of_measurement=UnitOfTemperature.CELSIUS,
            ),
            [StatisticData(start=hour, mean=mean, min=low, max=high)],
        )

    def _async_dispatch_measurement_event(self, record: dict[str, Any]) -> None:
        """Fire the measurement event, for automations and the device activity log."""
        self._async_fire(EVENT_BRAUN_MEASUREMENT, self.address, record)

    @callback
    def _async_fire(self, event_type: str, device_identifier: str, record: dict[str, Any]) -> None:
        """Fire an event tied to a device, so it shows in that device's activity."""
        device = dr.async_get(self.hass).async_get_device(identifiers={(DOMAIN, device_identifier)})
        event_data = {
            "device_id": device.id if device else None,
            "entry_id": self.entry.entry_id,
            "device_address": self.address,
            "device_name": self.entry.title,
            "model": self.profile.name,
            **record,
        }
        _LOGGER.debug("Firing %s event: %s", event_type, event_data)
        self.hass.bus.async_fire(event_type, event_data)

    async def async_unload(self) -> None:
        """Unload coordinator and clean up listeners."""
        if self._unsubscribe_ble:
            self._unsubscribe_ble()
            self._unsubscribe_ble = None
        self._unsubscribe_actions()
