# Braun Health BLE for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
[![GitHub Release](https://img.shields.io/github/v/release/cedhuf/ha-braun-ble?color=blue)](https://github.com/cedhuf/ha-braun-ble/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration for **Braun connected health devices** over local Bluetooth Low Energy (BLE), requiring **no cloud** and **no mobile app accounts**.

Tested and verified on the **Braun ThermoScan 7+ Connect (`IRT6575`)** and designed with an extensible profile architecture to support additional Braun BLE hardware (ThermoScan 4, ExactFit Blood Pressure Monitors).

---

## ✨ Features

- **100% Local & Private**: Direct BLE communication. No cloud dependency or Braun Family Care account required.
- **ESPHome Proxy Support**: Seamlessly syncs via local Bluetooth or any ESPHome Bluetooth Proxy.
- **Guided Onboarding**: Interactive pairing wizard in Home Assistant that decrypts AES keys directly using the on-screen 6-digit PIN.
- **Automatic Sync**: Passively listens for Bluetooth wake-up advertisements and retrieves new measurements automatically when you use the device.
- **Sensors Exposed**:
  - `sensor.<device>_temperature`: Body temperature in °C / °F, with age group, fever color status (normal/moderate/high), and measurement timestamp.
  - `sensor.<device>_battery`: Battery level percentage.
  - `sensor.<device>_stored_records`: Total historical records count in device memory.
- **Family Attribution Blueprint**: Ready-to-use actionable mobile notification to assign each reading to family members.
- **Apple Health (HealthKit) Bridge**: Seamlessly export readings into Apple Health via native iOS Shortcuts.

---

## 🩺 Supported Hardware

| Model | Device Type | Status | Tested By |
|---|---|---|---|
| **Braun ThermoScan 7+ Connect (`IRT6575`)** | Ear Thermometer | ✅ Full Support | [@cedhuf](https://github.com/cedhuf) |
| **Braun ThermoScan 4 Connect (`IRT3575`)** | Ear Thermometer | 🧪 Experimental | Community |
| **Braun ExactFit 5 Connect (`BPU5000`)** | Blood Pressure Monitor | 🚧 Profile Ready (Stub) | Contributions welcome |
| **Braun ExactFit 3 Connect (`BP6500`)** | Blood Pressure Monitor | 🚧 Profile Ready (Stub) | Contributions welcome |

> Have another Braun BLE device? Check our [Contributing Guide](CONTRIBUTING.md) to add your model!

---

## 📦 Installation

### Option 1: Via HACS (Recommended)

1. Open **HACS** in your Home Assistant dashboard.
2. Click the top-right menu (three dots) -> **Custom repositories**.
3. Add repository URL: `https://github.com/cedhuf/ha-braun-ble`
4. Category: **Integration**.
5. Click **Add**, find **Braun Health BLE**, and click **Download**.
6. Restart Home Assistant.

### Option 2: Manual Installation

1. Download the latest release `.zip` from [Releases](https://github.com/cedhuf/ha-braun-ble/releases).
2. Copy the `custom_components/ha_braun_ble` folder into your Home Assistant `<config_dir>/custom_components/` directory.
3. Restart Home Assistant.

---

## 🔄 Pairing Walkthrough

> [!IMPORTANT]
> The thermometer **must** be put into pairing mode from the **powered-off** state. Turning it on normally will only attempt to sync with already-paired devices.

1. In Home Assistant, go to **Settings** -> **Devices & Services** -> **Add Integration** -> **Braun Health BLE**.
2. Select your discovered thermometer or enter its MAC address.
3. **Enter Pairing Mode on the device**:
   - Ensure the thermometer is **completely powered off**.
   - Press and **HOLD** the Power button for ~5 seconds until the display turns **BLUE** with the Bluetooth icon and **`bt`** flashing.
   - Click **Submit** in Home Assistant.
4. **Enter the 6-Digit PIN**:
   - The thermometer screen will display a 6-digit number.
   - Type these 6 digits into the Home Assistant prompt.
   - Home Assistant will derive the session AES keys, verify the connection, and finalize setup!

---

## 👨‍👩‍👧‍👦 Family Attribution & Apple Health

Braun thermometers do not have per-person buttons on the device itself. Home Assistant makes attributing readings simple:

### 1. Actionable Notification Blueprint
Use our included blueprint:
[`blueprints/automation/ha_braun_ble/person_attribution.yaml`](blueprints/automation/ha_braun_ble/person_attribution.yaml)

Whenever someone takes a temperature reading, your phone receives a push notification:
> **🌡️ Braun Measurement: 38.4°C (High Fever)**  
> *Who is this temperature reading for?*  
> `[ Alice ]` `[ Bob ]` `[ Charlie ]`

Tapping a name immediately writes the temperature to that person's dedicated sensor/helper.

### 2. Apple Health (HealthKit) Integration
See our step-by-step guide in [docs/apple-health-setup.md](docs/apple-health-setup.md) to log temperature measurements directly into the iOS Health app via Apple Shortcuts.

---

## 🔬 Protocol & Technical Documentation

For details on the Kaz/Braun GATT layout, reverse engineering findings, and AES-CCM frames, refer to [docs/thermoscan-7-findings.md](docs/thermoscan-7-findings.md).

---

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on submitting pull requests and adding support for additional Braun BLE health devices.

## 📄 License

This project is licensed under the [MIT License](LICENSE).
