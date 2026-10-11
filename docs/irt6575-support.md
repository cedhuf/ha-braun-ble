# Braun ThermoScan 7+ Connect (IRT6575) support

**Status: Supported.** Owner-qualified on one device: pairing, live sync, record
acknowledgement, attribution and age profile were all exercised on real hardware.

## Scope and evidence

| | |
| --- | --- |
| Device | Braun ThermoScan 7+ Connect `IRT6575`, made by Kaz (Helen of Troy) |
| Identity read over BLE | Model number `TS7+`, firmware `1.2.0`, software `1.2.0` |
| Captures | 2026-10-11, macOS CoreBluetooth (bleak) next to the device, and Home Assistant 2026.10.1 through an ESPHome Bluetooth proxy |
| Writes performed | Only the documented record commands (`00 00` read, `01 00` acknowledge) and the authentication response. No setting, clock or firmware write. |

Evidence levels:

- **Device**: observed on the device, with the raw bytes below.
- **Inferred**: consistent with every capture, but not isolated by a dedicated test.
- **Unconfirmed**: hypothesis or open question.

## Advertisement

**Device.** Passive advertisements carry no local name, only:

- the record service UUID `aeb23580-80b6-432d-9b5a-57ff6feea94e`;
- a second 128-bit UUID `aeb23580-80b6-432d-9b5a-<reversed MAC>`;
- manufacturer data under ids `0x0001` and `0x8001`, both holding the MAC.

The name `TS7+` only comes in the scan response, so passive scanners such as
ESPHome proxies never see it. Discovery therefore matches the record service UUID.

The advertisement payload is identical at every power-on. Home Assistant drops
unchanged advertisements, so the integration clears the address history after
each session (`bluetooth.async_clear_advertisement_history`, Home Assistant 2026.6+).

## GATT layout

**Device**, from a full service discovery.

| Service | Characteristic | Properties | Content |
| --- | --- | --- | --- |
| `180a` Device Information | `2a24`, `2a26`, `2a28`... | read | Model `TS7+`, firmware and software `1.2.0` |
| `180f` Battery | `2a19` | read | Battery level, plain |
| `abe0f4c5-…` | `8de5fe92-…` | read | Challenge request, 17 bytes |
| | `fd700b4a-…` | write | Challenge response, 17 bytes |
| | `b97838b9-…` | notify | Key recovery during pairing |
| `aeb23580-80b6-432d-9b5a-57ff6feea94e` | `6be10cf5-…` | read, write | Device clock (encrypted) |
| | `a37d2f83-…` | read, write | Unknown (encrypted), see settings below |
| | `fbacb31a-…` | indicate | Final temperature, live |
| | `01766d60-…` | read | New-record count (encrypted) |
| | `220acbcf-…` | write | Record commands (encrypted) |
| | `0fc7830b-…` | notify | Records (encrypted) |
| `bdf86a20-…` | `49e63a0c-…`, `7cc7a24c-…`, `5c21b6dd-…` | write, notify | Unknown, nothing received while subscribed |
| `d874aea1-…` | `825ee269-…` | write | Unknown, never written (possible firmware update path) |

## Encryption

**Device.** Every protected frame is AES-128-CCM with a 16-byte tag:

- frame: `[counter (1)] || ciphertext || tag (16)`;
- nonce: `[session IV (12)] || [counter (1)]`;
- additional authenticated data: `[counter (1)]`.

### Pairing and key recovery

**Device** (pairing succeeds with this sequence; the constants come from the original
implementation, their origin is not documented here).

1. Turn the thermometer on from off by holding the power button about 5 seconds,
   until the screen is blue with `bt` flashing.
2. Subscribe to `b97838b9-…`, read the challenge, then write
   `018d54d5 || IV (12) || 5f` to the challenge response.
3. The device shows a 6-digit PIN and notifies 49 bytes: `00 || ciphertext (32) || tag (16)`.
4. The recovery key is `b"I'm Sorry Dave!."` with the six digits written as raw
   byte values (0 to 9) at indexes 5, 6, 9, 10, 14 and 15.
5. Decrypting gives `auth_key` (bytes 0 to 15) and `enc_key` (bytes 16 to 31).

### Session authentication

**Device.** At each connection: read the 17-byte challenge, encrypt its first 16 bytes
with `auth_key`, nonce `b"ARE U MY MOT\x00"` and AAD `00`, take 4 bytes of the result
starting at `challenge[16] % 16`, then write `digest (4) || session IV (12) || 01`
(17 bytes) to the challenge response.

## Records

### New-record count

**Device.** `01766d60-…` decrypts to 2 bytes: `18`, then the number of records not yet
synced. The meaning of `18` is unknown. The device only serves new records: the
Braun app shows only new ones for the same reason.

Captured: `18 01`, `18 02`, `18 03`, then `18 00` once read and acknowledged.

### Commands

**Device.** Encrypted `[command, index]` frames written to `220acbcf-…`, with the session
counter incremented on every write:

| Command | Effect |
| --- | --- |
| `00 nn` | The new record at index `nn` (0 is the oldest) arrives on `0fc7830b-…`. |
| `01 00` | Acknowledges the oldest new record: the count drops by one and the next record moves to index 0. |
| other `01 nn` / `nn 00` | Also clear records. Exact meaning **unconfirmed**; never sent by the integration. |

The index is the second byte. An early implementation sent it little-endian
(`01 00` for index 1), which silently acknowledged records instead of reading them.

### Record layout

**Device**, 21 bytes once decrypted, big-endian:

| Bytes | Content |
| --- | --- |
| `0` | Index that was requested |
| `1..3` | `00 00 00` so far |
| `4` | Sequence number, incremented by every measurement |
| `5` | `00` so far |
| `6..9` | Measurement time, Unix seconds, UTC (device clock about 2 s ahead) |
| `10..11` | `00 01` so far |
| `12..15` | Body temperature, float32, °C |
| `16` | Low two bits: age profile (`1` 0-3 months, `2` 3-36 months, `3` over 36 months). `0x08` always set, meaning unknown. |
| `17..20` | Ambient temperature, float32, °C |

Captured examples:

```text
0000000043006acb6978000142123d710b41c66666   36.56 °C, ambient 24.8 °C, over 36 months
0000000053006acb87160001421328f60941c00000   36.79 °C, ambient 24.0 °C, 0-3 months
0000000054006acb871d0001421328f60a41c0cccd   36.79 °C, ambient 24.1 °C, 3-36 months
```

### Live measurements

**Device.** While a client stays connected, every measurement triggers an indication
on `fbacb31a-…` and the new-record count goes up at once. Decrypted, the indication is
10 bytes, little-endian: body temperature (float32), ambient temperature (float32),
then `00 0b`. The integration only uses it as a trigger and reads the full record.

The device keeps the connection while it is on and drops it when it switches itself
off, about 58 seconds after the last measurement.

## Clock

**Device.** `6be10cf5-…` decrypts to `00 || Unix time (4, UTC) || 00 00 || UTC offset in
seconds (2)`, for example `006acb68cd00001c20` (offset 7200 s). It was accurate to
about 20 s. Writing it was not tested.

## Settings

**Device, negative result.** With one session open, the age profile was cycled through
its three values and night mode toggled on and off, reading every readable
characteristic after each change. Nothing tracked the settings:

- the clock only advanced;
- the new-record count did not change once decrypted;
- `a37d2f83-…` decrypts to 7 bytes, `00 || 4-byte counter || 2 bytes`, whose values
  (`92 00`, `8e 00`, `8f 00`, `8d 00`, `8e 00`) do not follow the changes. **Unconfirmed**:
  an internal sensor reading.

The age profile is only known afterwards, from byte 16 of each record. Night mode
does not appear anywhere. Changing either from Home Assistant is not possible with
what is known, and the Braun app cannot do it either.

## Open questions

- Meaning of the count prefix `18`, of bit `0x08` in byte 16, and of bytes 1 to 3, 5,
  10 and 11 of a record.
- Purpose of the `bdf86a20-…` and `d874aea1-…` services. They are not written, see the
  [scope policy](scope-policy.md).
- Whether the ThermoScan 4 Connect (`IRT3575`) speaks the same protocol. Its profile
  reuses this one but is untested.
