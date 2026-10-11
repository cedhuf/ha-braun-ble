# Contributing to Braun Health BLE (`ha-braun-ble`)

Thank you for your interest in contributing to this project! We welcome support for additional Braun/Kaz BLE health devices, such as connected blood pressure monitors (ExactFit 3 / ExactFit 5) and other thermometer models.

---

## Architecture Overview

Similar to [`ha-govee-led-ble`](https://github.com/teh-hippo/ha-govee-led-ble), this integration uses a modular, profile-driven architecture:

- **[`models.py`](file:///custom_components/ha_braun_ble/models.py)**: Defines `BraunModelProfile` capabilities, BLE advertising name prefixes, and measurement decoders.
- **[`crypto.py`](file:///custom_components/ha_braun_ble/crypto.py)**: Shared AES-CCM cipher routines and PIN-based key derivation.
- **[`coordinator.py`](file:///custom_components/ha_braun_ble/coordinator.py)**: Manages passive BLE detection, active connection, session handshake, and record syncing.
- **[`sensor.py`](file:///custom_components/ha_braun_ble/sensor.py)**: Exposes standard Home Assistant sensors for temperature, blood pressure, battery, and stored records.

---

## Adding Support for a New Device Model

To add support for a new model (e.g. Braun ExactFit Blood Pressure Monitor):

### 1. Identify Model & Bluetooth Advertisement
Run a BLE scanner or ESPHome Bluetooth proxy to capture the device advertisement name and MAC address:
- Example: `TS7+`, `BP5000`, `BP6500`.

### 2. Verify GATT Layout & Protocol
Most modern Braun connected devices share the Helen of Troy / Kaz BLE chipset:
- Check whether the device exposes the `8de5fe92...` / `fd700b4a...` challenge characteristics.
- If it uses standard Bluetooth SIG services (e.g. Blood Pressure Service `0x1810` / Measurement `0x2A35`), document the GATT profile in `docs/<device>-findings.md`.

### 3. Add Model Profile in `models.py`
Register your device in `SUPPORTED_MODELS`:

```python
SUPPORTED_MODELS["BPU5000"] = BraunModelProfile(
    model_id="BPU5000",
    name="Braun ExactFit 5 Connect",
    device_type=DeviceType.BLOOD_PRESSURE,
    ble_name_prefixes=["BP5", "BPU5000"],
    has_history=True,
    record_parser=parse_blood_pressure_record,
)
```

### 4. Implement Record Parser
Write the byte decoder in `models.py` to extract measurements (systolic, diastolic, pulse, irregular heartbeat flag) from the decrypted payload:

```python
def parse_blood_pressure_record(payload: bytes) -> dict[str, Any]:
    ...
```

---

## Submitting Pull Requests

1. Fork the repository and create your feature branch:
   ```bash
   git checkout -b feat/support-bpu5000
   ```
2. Ensure your changes are formatted and adhere to Python typing standards.
3. Include device captures or sample payloads (with any private serial numbers masked).
4. Open a pull request against `main`.
