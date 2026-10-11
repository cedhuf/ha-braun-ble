# Apple Health (HealthKit) Integration Guide

This guide explains how to automatically log body temperature readings from your Braun ThermoScan into **Apple Health** (HealthKit).

---

## Background & Architecture

The Home Assistant iOS Companion App allows reading data from Apple Health (step counts, Apple Watch battery, etc.), but **Apple strictly restricts silent background writing** into HealthKit from third-party apps without user confirmation.

The cleanest, most reliable and native method on iOS is using Apple's built-in **Shortcuts** app, which has native direct read/write privileges for HealthKit.

---

## Method 1: Interactive Notification with Shortcut Launch (Recommended)

Whenever a new measurement arrives in Home Assistant, an actionable push notification is sent to your iPhone. Tapping the notification triggers the shortcut and records the sample into Apple Health.

### 1. Create the iOS Shortcut ("Log Temperature")

1. Open the **Shortcuts** app on your iPhone.
2. Tap **+** to create a new shortcut named **`Log Temperature`**.
3. Add the action **"Get Shortcut Input"**.
4. Add the action **"Log Health Sample"**:
   - Type: **Body Temperature**
   - Value: Select *Shortcut Input* (as *Number*)
   - Unit: **°C** (or **°F**)
   - Date: **Current Date**
5. Save the shortcut.

### 2. Home Assistant Automation

In Home Assistant, configure an automation to send a notification linking to the shortcut:

```yaml
alias: "Braun BLE - Log to Apple Health"
description: "Send push notification to iPhone with a direct shortcut link"
trigger:
  - platform: event
    event_type: ha_braun_ble_measurement
action:
  - service: notify.notify
    data:
      title: "🌡️ Braun ThermoScan: {{ trigger.event.data.temperature }}°C"
      message: "Tap to record in Apple Health"
      data:
        url: "shortcuts://run-shortcut?name=Log%20Temperature&input={{ trigger.event.data.temperature }}"
```

---

## Method 2: Personal iOS Automation (Fully Automated)

To log samples automatically without tapping:

1. In the iOS **Shortcuts** app, navigate to the **Automation** tab.
2. Create a new personal automation:
   - Trigger: E.g., when receiving an HA notification or webhook.
   - Uncheck **"Ask Before Running"**.
3. In the action sequence:
   - Use the Home Assistant action **"Get state of entity"** to fetch `sensor.braun_thermoscan_7_connect_temperature`.
   - Add the action **"Log Health Sample"** with the retrieved temperature.
