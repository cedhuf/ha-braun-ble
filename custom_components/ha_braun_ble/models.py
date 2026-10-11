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
class BraunModelProfile:
    """One supported Braun model."""

    model_id: str
    name: str
    ble_name_prefixes: tuple[str, ...]
    # Runs one connected session, handing records to the coordinator until disconnected.
    run_session: SessionRunner
    kind: MeasurementKind


SUPPORTED_MODELS: dict[str, BraunModelProfile] = {
    profile.model_id: profile
    for profile in (
        BraunModelProfile(
            model_id="IRT6575",
            name="Braun ThermoScan 7+ Connect",
            ble_name_prefixes=("TS7", "IRT6575", "ThermoScan 7"),
            run_session=thermoscan.async_run_session,
            kind=TEMPERATURE,
        ),
        BraunModelProfile(
            model_id="IRT3575",
            name="Braun ThermoScan 4 Connect",
            ble_name_prefixes=("TS4", "IRT3575", "ThermoScan 4"),
            run_session=thermoscan.async_run_session,
            kind=TEMPERATURE,
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
