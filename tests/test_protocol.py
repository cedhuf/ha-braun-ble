import os

import pytest
from cryptography.exceptions import InvalidTag

from ha_braun_ble.crypto import (
    compute_challenge_response,
    decrypt_frame,
    derive_recovery_key,
    encrypt_frame,
)
from ha_braun_ble.models import SUPPORTED_MODELS, get_model_profile_by_name, parse_thermoscan_record


def test_recovery_key_places_digits_as_raw_bytes():
    key = derive_recovery_key("123456")
    assert key == b"I'm S\x01\x02ry\x03\x04ave\x05\x06"
    assert derive_recovery_key("123456", as_ascii=True) == b"I'm S12ry34ave56"


@pytest.mark.parametrize("pin", ["12345", "12a456", ""])
def test_recovery_key_rejects_bad_pin(pin):
    with pytest.raises(ValueError):
        derive_recovery_key(pin)


def test_pairing_keys_decrypt_with_pin_only():
    iv = os.urandom(12)
    keys = os.urandom(32)
    frame = encrypt_frame(keys, derive_recovery_key("482913"), iv, counter=0)

    assert len(frame) == 49
    assert decrypt_frame(frame, derive_recovery_key("482913"), iv) == keys
    with pytest.raises(InvalidTag):
        decrypt_frame(frame, derive_recovery_key("482914"), iv)


def test_frame_counter_is_authenticated():
    key, iv = os.urandom(16), os.urandom(12)
    frame = bytearray(encrypt_frame(b"\x05\x00", key, iv, counter=3))
    frame[0] = 4
    with pytest.raises(InvalidTag):
        decrypt_frame(bytes(frame), key, iv)


def test_challenge_response_layout():
    iv = os.urandom(12)
    challenge = os.urandom(17)
    resp = compute_challenge_response(challenge, os.urandom(16), iv)

    assert len(resp) == 17
    assert resp[4:16] == iv
    assert resp[-1:] == b"\x01"


def test_parse_record_full():
    payload = (
        (5).to_bytes(2, "little")
        + (3712).to_bytes(2, "little")
        + bytes([0b0110])  # age 36m+, fever moderate
        + (2026).to_bytes(2, "little")
        + bytes([10, 11, 8, 30, 0])
    )
    rec = parse_thermoscan_record(payload)

    assert rec["record_index"] == 5
    assert rec["temperature"] == 37.1
    assert rec["unit"] == "°C"
    assert rec["age_group"] == "36m+"
    assert rec["fever_status"] == "moderate"
    assert rec["timestamp"] == "2026-10-11T08:30:00"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(375, 37.5), (3712, 37.1), (0xF173, 37.1), (1000, None)],
)
def test_parse_record_temperature_formats(raw, expected):
    rec = parse_thermoscan_record(b"\x00\x00" + raw.to_bytes(2, "little"))
    assert rec.get("temperature") == expected


def test_model_lookup():
    assert get_model_profile_by_name("TS7+") is SUPPORTED_MODELS["IRT6575"]
    assert get_model_profile_by_name("ts4") is SUPPORTED_MODELS["IRT3575"]
    assert get_model_profile_by_name(None) is SUPPORTED_MODELS["IRT6575"]
    assert get_model_profile_by_name("unknown") is SUPPORTED_MODELS["IRT6575"]
