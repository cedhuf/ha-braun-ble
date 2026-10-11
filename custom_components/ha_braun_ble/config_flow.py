"""Config flow for Braun Health BLE integration."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import ConfigEntry, ConfigSubentryFlow, SubentryFlowResult
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import EntitySelector, EntitySelectorConfig

from .const import (
    CHALLENGE_RECOVERY_UUID,
    CHALLENGE_REQUEST_UUID,
    CHALLENGE_RESPONSE_UUID,
    CONF_AUTH_KEY,
    CONF_ENC_KEY,
    CONF_MODEL,
    CONF_PERSON,
    CONF_PIN,
    DOMAIN,
    RECORD_SERVICE_UUID,
    RECOVERY_MAGIC,
    SUBENTRY_PERSON,
)
from .crypto import (
    decrypt_frame,
    derive_recovery_key,
)
from .models import SUPPORTED_MODELS, get_model_profile_by_name

_LOGGER = logging.getLogger(__name__)


class BraunBleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Braun BLE devices."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types this device supports."""
        return {SUBENTRY_PERSON: PersonSubentryFlow}

    def __init__(self) -> None:
        """Initialize flow state."""
        self._discovered_devices: dict[str, str] = {}
        self._address: str | None = None
        self._device_name: str | None = None
        self._recovery_iv: bytes | None = None
        self._encrypted_keys: bytes | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle discovery initiated by Bluetooth scanner."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._address = discovery_info.address
        self._device_name = discovery_info.name or f"Braun {discovery_info.address}"
        return await self.async_step_pairing_prompt()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual setup or device selection."""
        if user_input is not None:
            choice = user_input[CONF_ADDRESS]
            if choice == "manual_keys":
                return await self.async_step_manual_keys()
            if choice == "manual":
                return await self.async_step_manual_address()
            return await self._async_select_address(choice)

        configured_addresses = {entry.unique_id for entry in self._async_current_entries()}
        for service_info in bluetooth.async_discovered_service_info(self.hass):
            addr = service_info.address
            if addr in configured_addresses:
                continue
            name = service_info.name or ""
            if RECORD_SERVICE_UUID in service_info.service_uuids or name.startswith(("TS7", "TS4")):
                self._discovered_devices[addr] = f"{name} ({addr})"

        options = {
            **self._discovered_devices,
            "manual": "Enter MAC address",
            "manual_keys": "Enter pre-extracted keys (advanced users)",
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(options)}),
        )

    async def async_step_manual_address(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Ask for the MAC address of a device that was not discovered."""
        if user_input is not None:
            return await self._async_select_address(user_input[CONF_ADDRESS].strip().upper())

        return self.async_show_form(
            step_id="manual_address",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
        )

    async def _async_select_address(self, address: str) -> FlowResult:
        """Bind the flow to an address and move on to pairing."""
        await self.async_set_unique_id(address)
        self._abort_if_unique_id_configured()

        self._address = address
        self._device_name = self._discovered_devices.get(address, f"Braun {address}")
        return await self.async_step_pairing_prompt()

    async def async_step_manual_keys(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Allow manual entry of pre-extracted auth and encryption keys."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip().upper()
            auth_key = user_input[CONF_AUTH_KEY].strip().lower()
            enc_key = user_input[CONF_ENC_KEY].strip().lower()

            if len(auth_key) != 32 or len(enc_key) != 32:
                errors["base"] = "invalid_key_length"
            else:
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()

                profile = get_model_profile_by_name(user_input.get(CONF_MODEL))
                return self.async_create_entry(
                    title=profile.name,
                    data={
                        CONF_ADDRESS: address,
                        CONF_AUTH_KEY: auth_key,
                        CONF_ENC_KEY: enc_key,
                        CONF_MODEL: profile.model_id,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS, default=self._address or ""): str,
                vol.Required(CONF_AUTH_KEY): str,
                vol.Required(CONF_ENC_KEY): str,
                vol.Optional(CONF_MODEL, default="IRT6575"): vol.In(
                    {m.model_id: m.name for m in SUPPORTED_MODELS.values()}
                ),
            }
        )
        return self.async_show_form(
            step_id="manual_keys",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_pairing_prompt(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Display pairing instructions (Power OFF -> hold button until blue screen with 'bt')."""
        if user_input is not None:
            # User confirmed device is in pairing mode; trigger BLE recovery handshake
            return await self._async_trigger_pairing()

        return self._show_pairing_form()

    def _show_pairing_form(self, error: str | None = None) -> FlowResult:
        """Show the pairing prompt, with an optional base error."""
        return self.async_show_form(
            step_id="pairing_prompt",
            data_schema=vol.Schema({}),
            description_placeholders={
                "device_name": self._device_name or self._address,
                "address": self._address,
            },
            errors={"base": error} if error else {},
        )

    async def _async_trigger_pairing(self) -> FlowResult:
        """Connect to device in pairing mode and request 6-digit PIN."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self._address, connectable=True
        )
        if not ble_device:
            return self._show_pairing_form("cannot_connect")

        keys_queue: asyncio.Queue[bytes] = asyncio.Queue()

        def _recovery_handler(_char, data):
            keys_queue.put_nowait(bytes(data))

        try:
            client = await establish_connection(
                BleakClient, ble_device, self._device_name or self._address, max_attempts=3
            )
        except Exception as err:
            _LOGGER.error("Pairing connection failed: %s", err)
            return self._show_pairing_form("cannot_connect")

        try:
            # Subscribe to recovery notifications
            await client.start_notify(CHALLENGE_RECOVERY_UUID, _recovery_handler)

            # Read challenge to wake crypto engine
            await client.read_gatt_char(CHALLENGE_REQUEST_UUID)

            # Generate recovery session IV and send magic recovery trigger
            session_iv = os.urandom(12)
            recovery_payload = RECOVERY_MAGIC + session_iv + b"\x5f"
            await client.write_gatt_char(CHALLENGE_RESPONSE_UUID, recovery_payload, response=True)

            _LOGGER.info("Recovery packet sent, waiting for device to display PIN...")
            # Wait for encrypted keys notification
            encrypted_payload = await asyncio.wait_for(keys_queue.get(), timeout=20.0)

            self._recovery_iv = session_iv
            self._encrypted_keys = encrypted_payload

        except asyncio.TimeoutError:
            return self._show_pairing_form("pairing_timeout")
        except Exception as err:
            _LOGGER.error("Error during pairing handshake: %s", err)
            return self._show_pairing_form("pairing_failed")
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        return await self.async_step_enter_pin()

    async def async_step_enter_pin(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Prompt user for the 6-digit PIN displayed on device screen."""
        errors: dict[str, str] = {}

        if user_input is not None:
            pin = user_input[CONF_PIN].strip()
            if len(pin) != 6 or not pin.isdigit():
                errors["base"] = "invalid_pin"
            else:
                try:
                    decrypted: bytes | None = None
                    # Try raw integer derivation (Kaz standard) then ascii
                    for as_ascii in (False, True):
                        try:
                            rec_key = derive_recovery_key(pin, as_ascii=as_ascii)
                            decrypted = decrypt_frame(
                                self._encrypted_keys, rec_key, self._recovery_iv
                            )
                            break
                        except Exception:
                            continue

                    if not decrypted or len(decrypted) < 32:
                        errors["base"] = "pin_decrypt_failed"
                    else:
                        auth_key = decrypted[:16].hex()
                        enc_key = decrypted[16:32].hex()

                        profile = get_model_profile_by_name(self._device_name)
                        return self.async_create_entry(
                            title=profile.name,
                            data={
                                CONF_ADDRESS: self._address,
                                CONF_AUTH_KEY: auth_key,
                                CONF_ENC_KEY: enc_key,
                                CONF_MODEL: profile.model_id,
                            },
                        )

                except Exception as err:
                    _LOGGER.error("Failed to decrypt keys with entered PIN: %s", err)
                    errors["base"] = "pin_decrypt_failed"

        return self.async_show_form(
            step_id="enter_pin",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PIN): str,
                }
            ),
            errors=errors,
        )


class PersonSubentryFlow(ConfigSubentryFlow):
    """Add a person measurements can be attributed to."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Ask for a name and an optional Home Assistant person."""
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Optional(CONF_PERSON): EntitySelector(EntitySelectorConfig(domain="person")),
                }
            ),
        )
