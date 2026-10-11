import os

import pytest
from cryptography.exceptions import InvalidTag

from ha_braun_ble.crypto import (
    compute_challenge_response,
    decrypt_frame,
    derive_recovery_key,
    encrypt_frame,
)
from ha_braun_ble.protocols.thermoscan import parse_record as parse_thermoscan_record


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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "000000003f006acb658700014211f5c30b41c80000",
            {"sequence": 0x3F, "timestamp": "2026-10-11T10:31:35+00:00", "temperature": 36.5,
             "ambient_temperature": 25.0},
        ),
        (
            "0200000045006acb697f000142123d710b41c66666",
            {"sequence": 0x45, "timestamp": "2026-10-11T10:48:31+00:00", "temperature": 36.6,
             "ambient_temperature": 24.8},
        ),
    ],
)
def test_parse_captured_ts7_records(raw, expected):
    rec = parse_thermoscan_record(bytes.fromhex(raw))
    assert rec == {"raw_hex": raw, "unit": "°C", **expected}


def test_parse_short_record_keeps_raw_only():
    assert parse_thermoscan_record(b"\x00\x01") == {"raw_hex": "0001"}
