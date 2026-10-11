"""Constants for the Braun Health BLE integration."""

DOMAIN = "ha_braun_ble"

# Configuration keys
CONF_AUTH_KEY = "auth_key"
CONF_ENC_KEY = "enc_key"
CONF_MODEL = "model"
CONF_PIN = "pin"
CONF_PERSON = "person"
CONF_DEFAULT_PERSON = "default_person"
CONF_PEOPLE = "people"
CONF_NOTIFY = "notify"

# Subentry type for the people measurements are attributed to
SUBENTRY_PERSON = "person"

# Event dispatched on new measurements
EVENT_BRAUN_MEASUREMENT = "ha_braun_ble_measurement"
EVENT_BRAUN_ATTRIBUTION = "ha_braun_ble_attribution"
EVENT_BRAUN_IGNORED = "ha_braun_ble_ignored"

# Standard GATT characteristics read on every model
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
MODEL_NUMBER_UUID = "00002a24-0000-1000-8000-00805f9b34fb"
FIRMWARE_REVISION_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
