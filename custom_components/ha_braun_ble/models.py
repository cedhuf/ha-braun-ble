"""Device model profiles and payload parsers for Braun BLE devices.

Inspired by the extensible profile architecture in ha-govee-led-ble.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import struct
from typing import Any, Callable


class DeviceType(StrEnum):
    """Supported Braun device categories."""
    THERMOMETER = "thermometer"
    BLOOD_PRESSURE = "blood_pressure"


@dataclass(frozen=True)
class BraunModelProfile:
    """Specification and capabilities of a supported Braun BLE model."""
    model_id: str
    name: str
    device_type: DeviceType
    ble_name_prefixes: list[str] = field(default_factory=list)
    has_history: bool = True
    record_parser: Callable[[bytes], dict[str, Any]] | None = None


def parse_thermoscan_record(payload: bytes) -> dict[str, Any]:
    """Parse a decrypted ThermoScan record (21 bytes, big-endian).

    Measured on a TS7+ with firmware 1.2.0: [0] index, [4] sequence number,
    [6:10] measurement time (Unix, UTC), [12:16] body temperature (float32, °C),
    [17:21] ambient temperature (float32, °C). The other bytes are unknown.
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
        "unit": "°C",
    }


def parse_blood_pressure_record(payload: bytes) -> dict[str, Any]:
    """Stub parser for Braun ExactFit Blood Pressure Monitors.

    Extracts systolic, diastolic, pulse and irregular heartbeat flags.
    Standard Bluetooth Health SIG Blood Pressure Measurement format (0x2A35)
    or Kaz proprietary frame.
    """
    result: dict[str, Any] = {
        "raw_hex": payload.hex(),
        "length": len(payload),
    }
    if len(payload) >= 6:
        # Standard format: flags (1), systolic (2), diastolic (2), map (2), pulse (2)
        systolic = int.from_bytes(payload[1:3], "little")
        diastolic = int.from_bytes(payload[3:5], "little")
        result["systolic"] = systolic
        result["diastolic"] = diastolic
        result["unit"] = "mmHg"
        if len(payload) >= 8:
            result["pulse"] = int.from_bytes(payload[6:8], "little")
    return result


# Model Profile Registry
SUPPORTED_MODELS: dict[str, BraunModelProfile] = {
    "IRT6575": BraunModelProfile(
        model_id="IRT6575",
        name="Braun ThermoScan 7+ Connect",
        device_type=DeviceType.THERMOMETER,
        ble_name_prefixes=["TS7", "IRT6575", "ThermoScan 7"],
        has_history=True,
        record_parser=parse_thermoscan_record,
    ),
    "IRT3575": BraunModelProfile(
        model_id="IRT3575",
        name="Braun ThermoScan 4 Connect",
        device_type=DeviceType.THERMOMETER,
        ble_name_prefixes=["TS4", "IRT3575", "ThermoScan 4"],
        has_history=True,
        record_parser=parse_thermoscan_record,
    ),
    "BPU5000": BraunModelProfile(
        model_id="BPU5000",
        name="Braun ExactFit 5 Connect",
        device_type=DeviceType.BLOOD_PRESSURE,
        ble_name_prefixes=["BP5", "BPU5000", "ExactFit 5"],
        has_history=True,
        record_parser=parse_blood_pressure_record,
    ),
    "BP6500": BraunModelProfile(
        model_id="BP6500",
        name="Braun ExactFit 3 Connect",
        device_type=DeviceType.BLOOD_PRESSURE,
        ble_name_prefixes=["BP3", "BP6500", "ExactFit 3"],
        has_history=True,
        record_parser=parse_blood_pressure_record,
    ),
}

DEFAULT_MODEL = SUPPORTED_MODELS["IRT6575"]


def get_model_profile_by_name(name: str | None) -> BraunModelProfile:
    """Find a model profile matching the BLE advertised name."""
    if not name:
        return DEFAULT_MODEL
    name_clean = name.strip()
    for profile in SUPPORTED_MODELS.values():
        for prefix in profile.ble_name_prefixes:
            if prefix.lower() in name_clean.lower():
                return profile
    return DEFAULT_MODEL
