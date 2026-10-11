# Contributing to Braun Health BLE (`ha-braun-ble`)

Support for more Braun BLE health devices is welcome. A new model should not need changes to the core.

---

## Architecture

Inspired by [`ha-govee-led-ble`](https://github.com/teh-hippo/ha-govee-led-ble): every exact model has a profile that declares what it is, and the core never names a model.

| Part | File | Role |
|---|---|---|
| Model profile | `models.py` | Exact model id, display name, BLE name prefixes, advertised service UUID, the protocol's session runner, the measurement kind, an optional `PinPairing`, device users and whether a battery is reported |
| Protocol | `protocols/<family>.py` | Pairing when needed, the Bluetooth session, reading and acknowledging records, decoding them into a record dict. `thermoscan.py` (encrypted, PIN) and `exactfit.py` (plain, standard blood pressure layout) |
| Measurement kind | `kinds.py` | Record fields, device and per-person sensors, long-term statistics, the short text used in notifications and the activity log |
| Core | `coordinator.py`, `sensor.py`, `button.py`, `messages.py`, `logbook.py` | Sessions, people, the attribution queue, notifications, statistics, events |

A protocol session receives the coordinator, a connected `BleakClient` and an `asyncio.Event` set on disconnection. It awaits `coordinator.async_add_record(record)` for each measurement, `await coordinator.async_synced()` after each batch, and may fill `coordinator.data` with `battery`, `model_number` and `firmware`. A record carries at least `timestamp` (ISO 8601, UTC), the kind's value fields and `raw_hex`, plus `user` when the device has its own users.

---

## Adding a model

1. **Capture the advertisement** (local name, service UUIDs, manufacturer data) and the GATT layout. Document them in `docs/<model>-support.md`, following [the ThermoScan one](docs/irt6575-support.md) and the [scope policy](docs/scope-policy.md), with sample payloads and serial numbers masked.
2. **Reuse or write a protocol.** A model that speaks an existing protocol only needs a profile. Otherwise add `protocols/<family>.py` with `async_run_session` and a record parser, plus a test decoding captured payloads in `tests/`.
3. **Reuse or add a measurement kind** in `kinds.py`, with its translations in `translations/*.json`.
4. **Register the profile** in `SUPPORTED_MODELS`, and add a Bluetooth matcher to `manifest.json`.

Only claim support for a model after testing it on the real device.

---

## Pull requests

1. Fork the repository and create a branch per model, for example `feat/support-bua6350`.
2. Run `uv run --group dev ruff check .` and `uv run --group dev pytest`.
3. Include captures or sample payloads, with serial numbers and addresses masked.
4. Open the pull request against `main`.
