# Braun Health BLE for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/default)
[![GitHub Release](https://img.shields.io/github/v/release/cedhuf/ha-braun-ble?color=blue)](https://github.com/cedhuf/ha-braun-ble/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A Home Assistant custom integration for **Braun connected health devices** over local Bluetooth Low Energy (BLE), requiring **no cloud** and **no mobile app accounts**.

Tested and verified on the **Braun ThermoScan 7+ Connect (`IRT6575`)** and built so that each Braun model is a self-contained profile (see [CONTRIBUTING.md](CONTRIBUTING.md)).

---

## ✨ Features

- **100% Local & Private**: Direct BLE communication. No cloud dependency or Braun Family Care account required.
- **ESPHome Proxy Support**: Seamlessly syncs via local Bluetooth or any ESPHome Bluetooth Proxy.
- **Guided Onboarding**: Interactive pairing wizard in Home Assistant that decrypts AES keys directly using the on-screen 6-digit PIN.
- **Automatic Sync**: Passively listens for Bluetooth wake-up advertisements and retrieves new measurements automatically when you use the device.
- **Live Sync**: Stays connected while the thermometer is on, so each reading reaches Home Assistant within a second.
- **Per-Person Readings**: Declare the people who use the device; each gets their own device with a temperature sensor and long-term statistics at the real measurement time.
- **Apple Health (HealthKit) Bridge**: Seamlessly export readings into Apple Health via native iOS Shortcuts.

---

## 🩺 Supported Hardware

| Model | Device Type | Status | Tested By |
|---|---|---|---|
| **Braun ThermoScan 7+ Connect (`IRT6575`)** | Ear Thermometer | ✅ Full Support | [@cedhuf](https://github.com/cedhuf) |
| **Braun ThermoScan 4 Connect (`IRT3575`)** | Ear Thermometer | 🧪 Experimental | Community |

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

## 👨‍👩‍👧‍👦 People & Attribution

The thermometer does not know who is being measured, so every reading waits to be attributed.

1. **Declare people** at the end of the pairing wizard, or later with **Add person** on the thermometer's device page. A person only needs a first name; linking a Home Assistant person is optional, so children need no account.
2. **Take readings** as usual. Each one lands in the **Pending measurement** sensor (the oldest waiting reading, with its time and the number still waiting).
3. **Attribute them**, right away or the next day:
   - **On your phone**: pick the phones in the device options (or at the end of pairing). Each new reading sends a notification such as *"36.7 °C measured 11/10 13:35. Who was it for?"* with one button per person and **Ignore**. The notification disappears from every phone once the reading is attributed.
   - **In Home Assistant**: a notification (the bell) lists every reading still waiting, with a link to the thermometer.
   - **On the device page**: press **Assign to <name>**, or **Ignore pending measurement** for a failed reading. This always applies to the oldest waiting reading, shown by the **Pending measurement** sensor; the next one then shows up.

Phone buttons need the Home Assistant Companion app. Android shows at most three buttons per notification, so with more than two people use the device page.

Each person appears as their own device with a **Temperature** sensor (latest reading, kept across restarts) and a long-term statistic `ha_braun_ble:<id>_temperature` dated at the real measurement time, for the *Statistics graph* card. The sensor's own history is dated when the reading was attributed.

To skip attribution, pick a person under **Attribute every measurement automatically to** in the device options: every reading then goes straight to them. It is empty by default so that a guest's reading never lands in someone's history.

### Device sensors

| Sensor | Content |
|---|---|
| Last measurement | Latest reading, whoever it was for |
| Pending measurement | Oldest reading waiting, as text such as `36.7 °C · 11/10 13:35` |
| Battery | Battery level |
| Ambient temperature | Ambient temperature at the last reading (disabled by default) |
| Model, Firmware | Diagnostic |

**Pending measurement is text, not a number**, so it has no graph or statistics: it is a waiting list. Temperature curves live on **Last measurement** (every reading, whoever it was for) and on each person's **Temperature**. Without any person declared, readings are never queued and only **Last measurement** is updated, which is all you need for live use.

Events for custom automations: `ha_braun_ble_measurement` (every reading), `ha_braun_ble_attribution` and `ha_braun_ble_ignored`. They also appear in the device activity log.

### Apple Health (HealthKit)
See our step-by-step guide in [docs/apple-health-setup.md](docs/apple-health-setup.md) to log temperature measurements directly into the iOS Health app via Apple Shortcuts.

---

## 🔬 Protocol & Technical Documentation

For details on the Kaz/Braun GATT layout, reverse engineering findings, and AES-CCM frames, refer to [docs/thermoscan-7-findings.md](docs/thermoscan-7-findings.md).

---

## 🤝 Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on submitting pull requests and adding support for additional Braun BLE health devices.

## 📄 License

This project is licensed under the [MIT License](LICENSE).
