"""Device model profiles and payload parsers for Braun BLE devices.

Inspired by the extensible profile architecture in ha-govee-led-ble.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
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


def _decode_sfloat(raw: int) -> float:
    """Decode IEEE-11073 16-bit SFLOAT value."""
    mantissa = raw & 0x0FFF
    if mantissa >= 0x0800:
        mantissa -= 0x1000
    exponent = raw >> 12
    if exponent >= 0x08:
        exponent -= 0x10
    return mantissa * (10 ** exponent)


def parse_thermoscan_record(payload: bytes) -> dict[str, Any]:
    """Parse decrypted record from ThermoScan 7+ / ThermoScan 4.

    Expected record length varies between 6 and 14 bytes depending on firmware.
    Handles both fixed-point integer (tenths/hundredths °C) and IEEE-11073 SFLOAT formats.
    """
    result: dict[str, Any] = {
        "raw_hex": payload.hex(),
        "length": len(payload),
    }

    if len(payload) < 2:
        return result

    # Heuristic parsing of record index and temperature
    # ThermoScan records start with a 16-bit record index or sequence number
    if len(payload) >= 4:
        rec_idx = int.from_bytes(payload[0:2], "little")
        raw_temp = int.from_bytes(payload[2:4], "little")
        result["record_index"] = rec_idx

        # Test temperature interpretations
        temp_c: float | None = None
        if 320 <= raw_temp <= 440:
            temp_c = raw_temp / 10.0
        elif 3200 <= raw_temp <= 4400:
            temp_c = raw_temp / 100.0
        else:
            candidate = round(_decode_sfloat(raw_temp), 1)
            if 32.0 <= candidate <= 44.0:
                temp_c = candidate

        if temp_c is not None:
            result["temperature"] = round(temp_c, 1)
            result["unit"] = "°C"

    # Status / AgeSmart flag byte if present
    if len(payload) >= 5:
        flag = payload[4]
        # Age group (bits 0-1): 0 = 0-3m, 1 = 3-36m, 2 = 36m+
        age_code = flag & 0x03
        age_map = {0: "0-3m", 1: "3-36m", 2: "36m+"}
        result["age_group"] = age_map.get(age_code, "unknown")

        # Fever indicator (bits 2-3): 0 = normal (green), 1 = moderate (yellow), 2 = high (red)
        fever_code = (flag >> 2) & 0x03
        fever_map = {0: "normal", 1: "moderate", 2: "high"}
        result["fever_status"] = fever_map.get(fever_code, "unknown")

    # RTC Timestamp parsing if payload contains at least 11 bytes
    # Format: [year (2 bytes little), month (1), day (1), hour (1), minute (1), second (1)]
    if len(payload) >= 11:
        try:
            year = int.from_bytes(payload[5:7], "little")
            month, day, hour, minute, second = payload[7:12]
            if 2020 <= year <= 2040 and 1 <= month <= 12 and 1 <= day <= 31 and hour < 24 and minute < 60:
                result["timestamp"] = datetime(year, month, day, hour, minute, min(second, 59)).isoformat()
        except Exception:
            pass

    return result


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
