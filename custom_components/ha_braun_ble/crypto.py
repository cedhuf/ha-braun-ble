"""Cryptographic helpers for Braun BLE devices."""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from .const import AUTH_NONCE, RECOVERY_KEY_TEMPLATE


def derive_recovery_key(digits: str, as_ascii: bool = False) -> bytes:
    """Derive recovery AES key from the 6 digits shown on device.

    The digits are substituted at indices (5, 6, 9, 10, 14, 15) into
    the template b"I'm Sorry Dave!.".
    By default, digits are encoded as raw integers (e.g. 7 -> 0x07),
    matching Kaz/Braun device implementation.
    """
    cleaned = digits.strip()
    if len(cleaned) != 6 or not cleaned.isdigit():
        raise ValueError(f"Expected exactly 6 numeric digits, got '{digits}'")

    key = bytearray(RECOVERY_KEY_TEMPLATE)
    for pos, digit in zip((5, 6, 9, 10, 14, 15), cleaned):
        key[pos] = ord(digit) if as_ascii else int(digit)
    return bytes(key)


def decrypt_frame(frame: bytes, key: bytes, iv: bytes) -> bytes:
    """Decrypt an AES-CCM frame.

    Frame format: counter (1 byte) || ciphertext || 16-byte MAC tag.
    Nonce: 12-byte IV || counter (1 byte).
    AAD: counter (1 byte).
    """
    if len(frame) < 17:
        raise ValueError(f"Frame too short ({len(frame)} bytes)")
    counter = frame[:1]
    nonce = iv + counter
    return AESCCM(key, tag_length=16).decrypt(nonce, frame[1:], counter)


def encrypt_frame(plain: bytes, key: bytes, iv: bytes, counter: int) -> bytes:
    """Encrypt payload into an AES-CCM frame.

    Frame format: counter (1 byte) || ciphertext || 16-byte MAC tag.
    Nonce: 12-byte IV || counter (1 byte).
    AAD: counter (1 byte).
    """
    c = bytes([counter & 0xFF])
    nonce = iv + c
    ciphertext = AESCCM(key, tag_length=16).encrypt(nonce, plain, c)
    return c + ciphertext


def compute_challenge_response(challenge: bytes, auth_key: bytes, session_iv: bytes) -> bytes:
    """Compute 21-byte challenge response to authenticate with the device.

    1. Encrypt challenge[:16] with auth_key and nonce AUTH_NONCE + 0x00.
    2. Extract 4 bytes from digest starting at challenge[16] % 16.
    3. Return 4-byte slice + 12-byte session_iv + b'\\x01' (total 21 bytes).
    """
    if len(challenge) < 17:
        raise ValueError(f"Challenge too short ({len(challenge)} bytes)")
    digest = AESCCM(auth_key, tag_length=16).encrypt(
        AUTH_NONCE + b"\x00", challenge[:16], b"\x00"
    )
    offset = challenge[16] % 16
    response_slice = bytes(digest[(offset + i) % 16] for i in range(4))
    return response_slice + session_iv + b"\x01"
