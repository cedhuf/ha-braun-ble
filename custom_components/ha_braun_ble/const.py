"""Constants for the Braun Health BLE integration."""

DOMAIN = "ha_braun_ble"

# Configuration keys
CONF_AUTH_KEY = "auth_key"
CONF_ENC_KEY = "enc_key"
CONF_MODEL = "model"
CONF_PIN = "pin"

# Event dispatched on new measurements
EVENT_BRAUN_MEASUREMENT = "ha_braun_ble_measurement"

# GATT UUIDs (Kaz / Braun TS7 & TS4). The record service is also advertised, without a local name.
RECORD_SERVICE_UUID = "aeb23580-80b6-432d-9b5a-57ff6feea94e"
CHALLENGE_REQUEST_UUID = "8de5fe92-2b6e-4f23-acea-ea7aae6b44fe"
CHALLENGE_RESPONSE_UUID = "fd700b4a-845e-4f41-aafa-333378f07462"
CHALLENGE_RECOVERY_UUID = "b97838b9-2649-4c99-bbdc-0acf217300e3"
RECORD_COUNT_UUID = "01766d60-0f08-4366-9778-d5d6c470531b"
RECORD_INDEX_REQUEST_UUID = "220acbcf-3d5d-4720-82f3-88103d804fbb"
RECORD_NOTIFICATION_UUID = "0fc7830b-ce64-4364-8332-00a32f6aa8e2"
FINAL_TEMP_NOTIFICATION_UUID = "fbacb31a-6d77-4a8c-8c2d-f149ea9ff36e"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
RTC_TIME_UUID = "6be10cf5-a104-4fdc-ac1a-6d700e2ea239"

# Commands written (encrypted) to RECORD_INDEX_REQUEST_UUID: [command, index]
READ_OLDEST_RECORD = b"\x00\x00"
ACK_OLDEST_RECORD = b"\x01\x00"

# Cryptographic seeds and nonces
RECOVERY_MAGIC = bytes.fromhex("018d54d5")
RECOVERY_KEY_TEMPLATE = b"I'm Sorry Dave!."
AUTH_NONCE = b"ARE U MY MOT"
