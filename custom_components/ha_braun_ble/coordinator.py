"""Coordinator: Bluetooth sessions, people, attribution queue and notifications.

Nothing here depends on a model: protocols hand records over and kinds describe them.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth, persistent_notification
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
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_ALWAYS_ASK,
    CONF_DEFAULT_PERSON,
    CONF_DEVICE_USER,
    CONF_MODEL,
    CONF_NOTIFY,
    DOMAIN,
    EVENT_BRAUN_ATTRIBUTION,
    EVENT_BRAUN_IGNORED,
    EVENT_BRAUN_MEASUREMENT,
    SUBENTRY_PERSON,
)
from .kinds import Statistic
from .messages import text
from .models import BraunModelProfile, SUPPORTED_MODELS, get_model_profile_by_name

_LOGGER = logging.getLogger(__name__)


def _record_id(record: dict[str, Any]) -> str:
    """Identify a measurement by its time and its sequence number or device user."""
    suffix = record.get("sequence", record.get("user", ""))
    return f"{int(datetime.fromisoformat(record['timestamp']).timestamp())}_{suffix}"


class BraunDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """One Braun device: its sessions, its people and the measurements waiting for them."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"Braun BLE ({entry.title})",
        )
        self.entry = entry
        self.address: str = entry.unique_id or entry.data["address"]

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
            **dict.fromkeys(d.key for d in self.profile.kind.device_sensors),
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
        """Stay connected while the device is on, syncing each new measurement."""
        if self._sync_lock.locked():
            _LOGGER.debug("Session already open with %s, skipping", self.address)
            return

        async with self._sync_lock:
            try:
                await self._async_run_session()
            finally:
                # The devices send the same advertisement at every power-on, which
                # Home Assistant drops as unchanged unless the history is cleared.
                bluetooth.async_clear_advertisement_history(self.hass, self.address)

    async def _async_run_session(self) -> None:
        """Connect and let the model's protocol run the session until the device disconnects."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if not ble_device:
            _LOGGER.debug("Device %s not available in BLE cache", self.address)
            return

        disconnected = asyncio.Event()
        details = ble_device.details if isinstance(ble_device.details, dict) else {}
        source = details.get("source", "local adapter")
        _LOGGER.info("Connecting to Braun device %s through %s", self.address, source)
        try:
            client = await establish_connection(
                BleakClient,
                ble_device,
                self.entry.title,
                disconnected_callback=lambda _client: disconnected.set(),
                max_attempts=2,
            )
        except Exception as err:
            _LOGGER.debug("Could not connect to %s (device likely asleep): %s", self.address, err)
            return

        try:
            await self.profile.run_session(self, client, disconnected)
        except Exception as err:
            if client.is_connected:
                _LOGGER.warning("Sync failed with device %s: %s", self.address, err, exc_info=True)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
        _LOGGER.debug("Session with %s closed", self.address)

    async def async_add_record(self, record: dict[str, Any]) -> None:
        """Take a record from the protocol: attribute or queue it, then publish it."""
        kind = self.profile.kind
        record["kind"] = kind.key
        if kind.is_measurement(record):
            persons = self.entry.get_subentries_of_type(SUBENTRY_PERSON)
            default = None
            if not self.profile.device_users:
                default = self.entry.subentries.get(self.entry.options.get(CONF_DEFAULT_PERSON) or "")
            linked = None
            if record.get("user") and not self.entry.options.get(CONF_ALWAYS_ASK):
                linked = next((p for p in persons if p.data.get(CONF_DEVICE_USER) == record["user"]), None)
            if linked or default:
                await self._async_attribute(record, linked or default)
            elif persons:
                record["id"] = _record_id(record)
                self.pending.append(record)
                await self._store.async_save(self.pending)
                self._async_update_pending_notification()
                await self._async_notify_phones(record, persons)
        self._async_dispatch_measurement_event(record)
        self.data["latest_record"] = record
        if kind.is_measurement(record):
            for description in kind.device_sensors:
                self.data[description.key] = record[description.key]

    @callback
    def async_synced(self) -> None:
        """Note the end of a sync and refresh the entities."""
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
        lines = [text(self.hass, "pending_line", record) for record in self.pending]
        if device_id := self._device_id(self.address):
            lines += ["", text(self.hass, "pending_link", device=self.entry.title, device_id=device_id)]
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
        hour = datetime.fromisoformat(record["timestamp"]).replace(minute=0, second=0, microsecond=0)
        for statistic in self.profile.kind.statistics:
            await self._async_add_statistic(person, statistic, hour, record[statistic.field])

    async def _async_add_statistic(
        self, person: ConfigSubentry, statistic: Statistic, hour: datetime, value: float
    ) -> None:
        statistic_id = f"{DOMAIN}:{person.subentry_id.lower()}_{statistic.field}"
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
                name=f"{person.title} {self.entry.title}{statistic.name_suffix}",
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_class=statistic.unit_class,
                unit_of_measurement=statistic.unit,
            ),
            [StatisticData(start=hour, mean=mean, min=low, max=high)],
        )

    def _async_dispatch_measurement_event(self, record: dict[str, Any]) -> None:
        """Fire the measurement event, for automations and the device activity log."""
        self._async_fire(EVENT_BRAUN_MEASUREMENT, self.address, record)

    @callback
    def _async_fire(self, event_type: str, device_identifier: str, record: dict[str, Any]) -> None:
        """Fire an event tied to a device, so it shows in that device's activity."""
        event_data = {
            "device_id": self._device_id(device_identifier),
            "entry_id": self.entry.entry_id,
            "device_address": self.address,
            "device_name": self.entry.title,
            "model": self.profile.name,
            **record,
        }
        _LOGGER.debug("Firing %s event: %s", event_type, event_data)
        self.hass.bus.async_fire(event_type, event_data)

    @callback
    def _device_id(self, identifier: str) -> str | None:
        """Return the id of this entry's device with the given identifier."""
        # Identifiers are only unique within a config entry.
        for device in dr.async_entries_for_config_entry(dr.async_get(self.hass), self.entry.entry_id):
            if (DOMAIN, identifier) in device.identifiers:
                return device.id
        return None

    async def async_unload(self) -> None:
        """Unload coordinator and clean up listeners."""
        if self._unsubscribe_ble:
            self._unsubscribe_ble()
            self._unsubscribe_ble = None
        self._unsubscribe_actions()
