# Braun ExactFit 5 Connect (BUA6350) support

**Status: Research.** Not supported yet. Live measurements were captured and decoded
on real hardware; nothing is implemented in the integration.

## Scope and evidence

| | |
| --- | --- |
| Device | Braun ExactFit 5 Connect upper-arm blood pressure monitor `BUA6350`, made by Kaz USA |
| Identity read over BLE | Model `BLE/BUA6350`, firmware `1.0.14/A01.003`, hardware `1.0.0/A01.000`, software `1.0.14/A01.003`, manufacturer `Kaz USA, Inc` |
| Companion app | Braun Healthy Heart (not Braun Family Care, used by the thermometers) |
| Device features | Two users, `A` and `B`; date and time setting; Bluetooth pairing menu |
| Captures | 2026-10-11, macOS CoreBluetooth (bleak) next to the device |
| Writes performed | None. Only reads and notification subscriptions. |

Evidence levels: **Device** (observed, raw bytes below), **Inferred**, **Unconfirmed**,
as in the [ThermoScan document](irt6575-support.md).

## Advertisement

**Device.**

| Field | Value |
| --- | --- |
| Local name | `BUA6350` (seen by an active scanner; not yet checked on a passive ESPHome proxy) |
| Service UUID | `56484aae-a8eb-4a97-ac19-a8ea6373e05a` |
| Manufacturer data | id `515` (`0x0203`), 6 bytes, `4891c8fcff98` on the tested unit |

**Device.** The monitor advertises as soon as it is switched on for a normal
measurement, without using the pairing menu, and accepts a connection right away.

## GATT layout

**Device**, from a full service discovery.

| Service | Characteristic | Properties | Content |
| --- | --- | --- | --- |
| `180f` Battery | `2a19` | read, notify | Read `00`, then notified `82` repeatedly. Not a percentage; meaning **unconfirmed**. |
| `180a` Device Information | `2a23` to `2a2a`, `2a50` | read | Identity above, serial number, PnP id `010d0000001001` |
| `f000ffc0-0451-4000-b000-000000000000` | `f000ffc1-…`, `f000ffc2-…` | write, notify | Texas Instruments over-the-air firmware update. **Never touched**, see the [scope policy](scope-policy.md). |
| `56484aae-a8eb-4a97-ac19-a8ea6373e05a` | `2db34480-bce5-4bb7-9f56-55bd202317c5` | notify | **Measurements**, see below |
| | `77ab1c51-2f6b-4a7b-81af-5e301984bf13` | notify | Nothing received yet. **Unconfirmed**: cuff pressure during inflation. |
| | `c3a2ed78-b3f1-4086-ab3b-bf3c5685a745` | read | `0000` |
| `bb647f01-d352-48de-9015-d055b1355d7b` | `bc305904-03cd-4858-8ae0-b184f2a52898` | read, notify | Read refused with "Read Not Permitted" even right after pairing mode, so not a bonding requirement. Nothing notified. |
| | `6114ac81-2a71-4acc-ada5-555b63e8c5e1` | read, write | Device clock, see below |
| | `25775d68-eb3f-4ee5-961a-5312516cb0ca` | read | `02 3c 00 06`. **Inferred**: `02` is the number of users. Rest unknown. |
| | `fce1be76-a487-4331-96b0-53c8097e306c` | write, notify | Unknown |
| | `991dee0f-75c1-4c7c-93ed-78fef7f8e6db` | notify | Unknown, nothing received |
| | `53ebc2ce-…`, `598040af-…`, `deffe5de-…`, `d4a0c8c3-…`, `2df251d7-…` | write | Unknown, never written |

No encryption and no pairing were needed for anything below. macOS never triggered
a bonding request.

## Measurements

**Device.** A finished measurement is notified on `2db34480-…` in the standard
Bluetooth Blood Pressure Measurement layout (the one of characteristic `0x2A35`),
little-endian:

| Bytes | Content |
| --- | --- |
| `0` | Flags. `1e`: unit mmHg, time stamp, pulse, user id and measurement status present |
| `1..2` | Systolic, SFLOAT |
| `3..4` | Diastolic, SFLOAT |
| `5..6` | Mean arterial pressure, SFLOAT |
| `7..13` | Time stamp: year (2), month, day, hours, minutes, seconds; device local time |
| `14..15` | Pulse rate, SFLOAT |
| `16` | User id: `00` user A, `01` user B |
| `17..18` | Measurement status bits (standard: `0` body movement, `1` cuff too loose, `2` irregular pulse, `3..4` pulse range, `5` position) |

Captured, with the values shown on the screen:

```text
1e 7400 4900 5a00 ea07 0a 0b 0f 0f 00 5b00 00 0100   116/73, pulse 91, MAP 90, 15:15, user A, body movement
1e 8500 4600 5a00 ea07 0a 0b 0f 13 00 5a00 01 0000   133/70, pulse 90, MAP 90, 15:19, user B, no flag
```

The first capture followed a measurement the monitor had reported as an error a
few minutes earlier; the body-movement bit is consistent with it.

### Session timeline

**Device**, normal use from switched off, user B. Times from the start of the scan;
the monitor was switched on just after it:

| Time | Event |
| --- | --- |
| 13.6 s | Advertisement found |
| 17.3 s | Connected |
| 59.8 s | Measurement notified on `2db34480-…` |
| 118.9 s | Connection dropped by the monitor as it switched off, about 59 s after the measurement |

The same cycle as the ThermoScan: one session per use, ending when the device
switches off.

## Clock

**Device.** `6114ac81-…` reads `0a 0b ea07 0f 30 06 2f`: month 10, day 11, year 2026,
15:48:06, then one unknown byte. It is writable, which would let Home Assistant set
the monitor's time. **Unconfirmed**: the write format and whether the monitor
accepts it; never written.

## Not yet known

- **Stored history.** The monitor keeps 200 measurements per user, but nothing is sent
  for them on connection. Retrieving measurements taken out of range presumably needs
  a command from the Healthy Heart app, not identified.
- The battery value `82`, the `25775d68-…` bytes after `02`, and the purpose of the
  write-only characteristics.
- Whether a passive ESPHome proxy receives the local name, or only the service UUID.

## Planned support

- Discovery on the service UUID `56484aae-…`, setup without PIN or keys.
- One session per use: subscribe to `2db34480-…`, hand each measurement over until the
  monitor disconnects.
- Device users `A` and `B` linked to people, so measurements are attributed without
  the queue; the queue only for an unlinked user.
- Systolic, diastolic and pulse sensors on the device and on each person, with
  statistics at the measurement time; mean arterial pressure and status bits as
  attributes.
