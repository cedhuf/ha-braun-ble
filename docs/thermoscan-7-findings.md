# Braun ThermoScan 7+ Connect (IRT6575) - Reverse-Engineering & Protocol Findings

## Overview

The **Braun ThermoScan 7+ Connect** (model `IRT6575`, manufactured by Kaz Europe Sàrl / Helen of Troy) communicates over Bluetooth Low Energy (BLE). Its advertisements carry no local name: only the record service UUID `aeb23580-80b6-432d-9b5a-57ff6feea94e`, a second UUID ending with the reversed MAC address, and manufacturer data holding the MAC. The name `TS7+` only comes in the scan response, so passive scanners (ESPHome proxies) never see it.

All functional communications (except standard unauthenticated battery reading) are encrypted using authenticated **AES-CCM** with 128-bit keys.

---

## GATT Service Layout

The device implements the standard Kaz Medical BLE profile:

| UUID | Type | Properties | Description |
|---|---|---|---|
| `00002a19-0000-1000-8000-00805f9b34fb` | Read, Notify | Read | Battery Level (0-100%, unencrypted) |
| `8de5fe92-2b6e-4f23-acea-ea7aae6b44fe` | Read | Read | **Challenge Request** (17 bytes) |
| `fd700b4a-845e-4f41-aafa-333378f07462` | Write | Write | **Challenge Response** (17 bytes) |
| `b97838b9-2649-4c99-bbdc-0acf217300e3` | Notify | Notify | **Challenge Recovery Notification** (encrypted keys) |
| `01766d60-0f08-4366-9778-d5d6c470531b` | Read, Notify | Read | **Stored Record Count** (AES-CCM encrypted) |
| `220acbcf-3d5d-4720-82f3-88103d804fbb` | Write | Write | **Record Index Request** (AES-CCM encrypted) |
| `0fc7830b-ce64-4364-8332-00a32f6aa8e2` | Notify | Notify | **Record Payload Notification** (AES-CCM encrypted) |
| `fbacb31a-6d77-4a8c-8c2d-f149ea9ff36e` | Notify | Notify | Final Temperature Realtime Notification |
| `6be10cf5-a104-4fdc-ac1a-6d700e2ea239` | Read, Write | Read/Write | Device RTC Clock (Unix timestamp) |

---

## Cryptographic Mechanism

### 1. AES-CCM Specification
Every encrypted frame follows this layout:
- **Frame structure**: `[1-byte counter] || [ciphertext] || [16-byte MAC tag]`
- **Nonce (13 bytes)**: `[12-byte session IV] || [1-byte counter]`
- **Additional Authenticated Data (AAD)**: `[1-byte counter]`
- **Cipher**: AES-128 in CCM mode (`AESCCM(key, tag_length=16)`).

### 2. Device Pairing & Key Recovery
When entering pairing mode, the thermometer switches to bond recovery:
1. Device must be turned on from the **OFF** state by holding the Power button for 5 seconds until the display is **BLUE** with the Bluetooth icon and **"bt"** flashing.
2. The client subscribes to `CHALLENGE_RECOVERY_UUID`.
3. Client reads `CHALLENGE_REQUEST_UUID`.
4. Client generates a 12-byte random session IV and writes to `CHALLENGE_RESPONSE_UUID`:
   ```
   Payload = 0x018d54d5 (RECOVERY_MAGIC) || IV (12 bytes) || 0x5f
   ```
5. The device displays a **6-digit PIN** on its LCD.
6. The device emits a notification on `CHALLENGE_RECOVERY_UUID` containing 49 bytes:
   `[1-byte counter = 0x00] || [ciphertext: 32 bytes] || [16-byte tag]`.
7. **Recovery Key Derivation**:
   Template: `b"I'm Sorry Dave!."` (16 bytes).
   The 6 digits from the display are placed at byte indices `(5, 6, 9, 10, 14, 15)`.
   Each digit is encoded as a raw integer byte (`0` to `9`), e.g.:
   ```python
   key = bytearray(b"I'm Sorry Dave!.")
   for pos, digit in zip((5, 6, 9, 10, 14, 15), pin_str):
       key[pos] = int(digit)
   ```
8. Decrypting the payload with this recovery key yields:
   - `auth_key` (bytes 0..15): used for session authentication.
   - `enc_key` (bytes 16..31): used for all payload data encryption.

### 3. Session Authentication Handshake
At every subsequent connection:
1. Client reads 17 bytes from `CHALLENGE_REQUEST_UUID`.
2. Encrypt `challenge[:16]` using `auth_key` with nonce `b"ARE U MY MOT\x00"` and AAD `b"\x00"`.
3. Extract 4 bytes from the resulting digest starting at index `challenge[16] % 16`.
4. Client generates a new 12-byte random `session_iv`.
5. Client writes 17 bytes to `CHALLENGE_RESPONSE_UUID`:
   ```
   [4 digest bytes] || [12-byte session_iv] || 0x01
   ```
6. The connection is authenticated for the session.

### 4. Record Synchronization
The device only serves measurements not yet synced ("new" ones). Measured on firmware 1.2.0:

1. Read `RECORD_COUNT_UUID` and decrypt it: 2 bytes, `0x18` then the number of new records.
2. Write encrypted commands to `RECORD_INDEX_REQUEST_UUID`, as `[command, index]`, incrementing the session counter for each write:
   - `00 nn`: read new record `nn` (0 is the oldest). The record arrives as a notification on `RECORD_NOTIFICATION_UUID`.
   - `01 00`: acknowledge the oldest new record. The count drops by one and the next record moves to index 0. Other `01 nn` / `nn 00` values also clear records; their exact meaning is unknown.
3. A decrypted record is 21 bytes, big-endian:

| Bytes | Content |
|---|---|
| `0` | Index that was requested |
| `4` | Sequence number, incremented by every measurement |
| `6..9` | Measurement time, Unix seconds, UTC |
| `12..15` | Body temperature, float32, °C |
| `17..20` | Ambient temperature, float32, °C |
| others | Unknown (`5` = `00`, `10..11` = `00 01`, `16` = `0b` so far) |

`RTC_TIME_UUID` decrypts to `00` + Unix time (4 bytes, UTC) + `00 00` + UTC offset in seconds (2 bytes).

### 5. Live Measurements
While a client stays connected, the device sends an indication on `FINAL_TEMP_NOTIFICATION_UUID` as soon as a measurement is taken, and the new-record count goes up at the same time. Decrypted, the indication is 10 bytes, little-endian: body temperature (float32, °C), ambient temperature (float32, °C), then `00 0b`.

The device keeps the connection open while it is on and drops it when it turns itself off, about a minute after the last measurement. Its advertisement payload is identical at every power-on, so Home Assistant only reports it again once its advertisement history for the address is cleared (`bluetooth.async_clear_advertisement_history`, Home Assistant 2026.6+).
