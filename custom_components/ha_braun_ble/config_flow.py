"""Config flow for Braun Health BLE integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient
from bleak_retry_connector import establish_connection
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    ConfigSubentryData,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_AUTH_KEY,
    CONF_DEFAULT_PERSON,
    CONF_ENC_KEY,
    CONF_MODEL,
    CONF_NOTIFY,
    CONF_PEOPLE,
    CONF_PERSON,
    CONF_PIN,
    DOMAIN,
    SUBENTRY_PERSON,
)
from .models import (
    DEFAULT_MODEL,
    SUPPORTED_MODELS,
    BraunModelProfile,
    get_model_profile_by_name,
    profile_for_advertisement,
)

_LOGGER = logging.getLogger(__name__)


def _notify_selector(hass: HomeAssistant) -> SelectSelector:
    """Offer the phones running the Home Assistant app, which support action buttons."""
    services = hass.services.async_services_for_domain("notify")
    phones = sorted(name for name in services if name.startswith("mobile_app_"))
    return SelectSelector(SelectSelectorConfig(options=phones, multiple=True))


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

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return BraunOptionsFlow()

    def __init__(self) -> None:
        """Initialize flow state."""
        self._discovered_devices: dict[str, str] = {}
        self._discovered_profiles: dict[str, BraunModelProfile] = {}
        self._address: str | None = None
        self._device_name: str | None = None
        self._profile: BraunModelProfile = DEFAULT_MODEL
        self._pairing_state: tuple[bytes, bytes] | None = None
        self._title = ""
        self._data: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle discovery initiated by Bluetooth scanner."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        profile = profile_for_advertisement(discovery_info.name, discovery_info.service_uuids)
        if profile is None:
            return self.async_abort(reason="not_supported")
        self._address = discovery_info.address
        self._device_name = discovery_info.name or f"Braun {discovery_info.address}"
        self._profile = profile
        return await self._async_after_address()

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
            if profile := profile_for_advertisement(name, service_info.service_uuids):
                self._discovered_devices[addr] = f"{name} ({addr})"
                self._discovered_profiles[addr] = profile

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
        self._profile = self._discovered_profiles.get(address, DEFAULT_MODEL)
        return await self._async_after_address()

    async def _async_after_address(self) -> FlowResult:
        """Pair when the model needs it, otherwise go straight to the people step."""
        if self._profile.pairing is not None:
            return await self.async_step_pairing_prompt()
        self._title = self._profile.name
        self._data = {CONF_ADDRESS: self._address, CONF_MODEL: self._profile.model_id}
        return await self.async_step_people()

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
                self._title = profile.name
                self._data = {
                    CONF_ADDRESS: address,
                    CONF_AUTH_KEY: auth_key,
                    CONF_ENC_KEY: enc_key,
                    CONF_MODEL: profile.model_id,
                }
                return await self.async_step_people()

        schema = vol.Schema(
            {
                vol.Required(CONF_ADDRESS, default=self._address or ""): str,
                vol.Required(CONF_AUTH_KEY): str,
                vol.Required(CONF_ENC_KEY): str,
                vol.Optional(CONF_MODEL, default=DEFAULT_MODEL.model_id): vol.In(
                    {m.model_id: m.name for m in SUPPORTED_MODELS.values() if m.pairing}
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

        try:
            client = await establish_connection(
                BleakClient, ble_device, self._device_name or self._address, max_attempts=3
            )
        except Exception as err:
            _LOGGER.error("Pairing connection failed: %s", err)
            return self._show_pairing_form("cannot_connect")

        try:
            self._pairing_state = await self._profile.pairing.request(client)
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
            elif keys := self._profile.pairing.keys_from_pin(pin, *self._pairing_state):
                self._title = self._profile.name
                self._data = {
                    CONF_ADDRESS: self._address,
                    CONF_MODEL: self._profile.model_id,
                    **keys,
                }
                return await self.async_step_people()
            else:
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


    async def async_step_people(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Explain attribution and let the user declare people right away."""
        if user_input is not None:
            names = [name.strip() for name in user_input.get(CONF_PEOPLE, []) if name.strip()]
            return self.async_create_entry(
                title=self._title,
                data=self._data,
                options={CONF_NOTIFY: user_input.get(CONF_NOTIFY, [])},
                subentries=[
                    ConfigSubentryData(
                        data={CONF_NAME: name},
                        subentry_type=SUBENTRY_PERSON,
                        title=name,
                        unique_id=None,
                    )
                    for name in names
                ],
            )

        return self.async_show_form(
            step_id="people",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_PEOPLE): TextSelector(TextSelectorConfig(multiple=True)),
                    vol.Optional(CONF_NOTIFY): _notify_selector(self.hass),
                }
            ),
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


class BraunOptionsFlow(OptionsFlow):
    """Device options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose the phones to notify and an optional person to attribute everything to."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_NOTIFY, default=self.config_entry.options.get(CONF_NOTIFY, [])
                    ): _notify_selector(self.hass),
                    vol.Optional(
                        CONF_DEFAULT_PERSON,
                        description={"suggested_value": self.config_entry.options.get(CONF_DEFAULT_PERSON)},
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=person.subentry_id, label=person.title)
                                for person in self.config_entry.get_subentries_of_type(SUBENTRY_PERSON)
                            ]
                        )
                    ),
                }
            ),
        )
