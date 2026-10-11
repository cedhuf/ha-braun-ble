"""Exact-model profiles: each Braun model declares its protocol and what it measures."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import asyncio
from typing import TYPE_CHECKING

from bleak import BleakClient

from .kinds import TEMPERATURE, MeasurementKind
from .protocols import thermoscan

if TYPE_CHECKING:
    from .coordinator import BraunDataUpdateCoordinator

SessionRunner = Callable[
    ["BraunDataUpdateCoordinator", BleakClient, asyncio.Event], Awaitable[None]
]


@dataclass(frozen=True)
class PinPairing:
    """Pairing where the device shows a PIN that unlocks its keys."""

    # Puts a connected device into key recovery; returns what keys_from_pin needs.
    request: Callable[[BleakClient], Awaitable[tuple[bytes, bytes]]]
    # Returns the config entry data holding the keys, or None for a wrong PIN.
    keys_from_pin: Callable[[str, bytes, bytes], dict[str, str] | None]


@dataclass(frozen=True)
class BraunModelProfile:
    """One supported Braun model."""

    model_id: str
    name: str
    ble_name_prefixes: tuple[str, ...]
    # Advertised service UUID used to recognise the model.
    service_uuid: str
    # Runs one connected session, handing records to the coordinator until disconnected.
    run_session: SessionRunner
    kind: MeasurementKind
    pairing: PinPairing | None = None


THERMOSCAN_PAIRING = PinPairing(thermoscan.async_request_pin, thermoscan.keys_from_pin)

SUPPORTED_MODELS: dict[str, BraunModelProfile] = {
    profile.model_id: profile
    for profile in (
        BraunModelProfile(
            model_id="IRT6575",
            name="Braun ThermoScan 7+ Connect",
            ble_name_prefixes=("TS7", "IRT6575", "ThermoScan 7"),
            service_uuid=thermoscan.RECORD_SERVICE_UUID,
            run_session=thermoscan.async_run_session,
            kind=TEMPERATURE,
            pairing=THERMOSCAN_PAIRING,
        ),
        BraunModelProfile(
            model_id="IRT3575",
            name="Braun ThermoScan 4 Connect",
            ble_name_prefixes=("TS4", "IRT3575", "ThermoScan 4"),
            service_uuid=thermoscan.RECORD_SERVICE_UUID,
            run_session=thermoscan.async_run_session,
            kind=TEMPERATURE,
            pairing=THERMOSCAN_PAIRING,
        ),
    )
}

DEFAULT_MODEL = SUPPORTED_MODELS["IRT6575"]


def get_model_profile_by_name(name: str | None) -> BraunModelProfile:
    """Find a model profile matching the BLE advertised name."""
    if not name:
        return DEFAULT_MODEL
    for profile in SUPPORTED_MODELS.values():
        if any(prefix.lower() in name.lower() for prefix in profile.ble_name_prefixes):
            return profile
    return DEFAULT_MODEL


def profile_for_advertisement(name: str | None, service_uuids: list[str]) -> BraunModelProfile | None:
    """Recognise a model from its advertised service UUID or, failing that, its name."""
    for profile in SUPPORTED_MODELS.values():
        if profile.service_uuid in service_uuids:
            # Models sharing a service UUID are told apart by name when it is advertised.
            if name and any(p.lower() in name.lower() for p in profile.ble_name_prefixes):
                return profile
    for profile in SUPPORTED_MODELS.values():
        if profile.service_uuid in service_uuids or (
            name and any(p.lower() in name.lower() for p in profile.ble_name_prefixes)
        ):
            return profile
    return None
