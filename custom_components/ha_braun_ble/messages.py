"""Texts the integration writes itself: activity log, notifications, pending sensor.

Home Assistant only translates entity and flow strings, so these follow the server language.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import EVENT_BRAUN_ATTRIBUTION, EVENT_BRAUN_IGNORED, EVENT_BRAUN_MEASUREMENT

TEXTS = {
    "en": {
        EVENT_BRAUN_MEASUREMENT: "measured {temperature}",
        EVENT_BRAUN_ATTRIBUTION: "was attributed {temperature}, measured {time}",
        EVENT_BRAUN_IGNORED: "ignored the {temperature} measurement from {time}",
        "notify_message": "{temperature} measured {time}. Who was it for?",
        "ignore": "Ignore",
        "pending_title": "Braun measurements to attribute",
        "pending_value": "{temperature} · {time}",
        "pending_line": "- {temperature}, {time}",
        "pending_link": "[Open {device}](/config/devices/device/{device_id})",
    },
    "fr": {
        EVENT_BRAUN_MEASUREMENT: "a mesuré {temperature}",
        EVENT_BRAUN_ATTRIBUTION: "s'est vu attribuer {temperature}, mesurés le {time}",
        EVENT_BRAUN_IGNORED: "a ignoré la mesure de {temperature} du {time}",
        "notify_message": "{temperature} mesurés le {time}. Pour qui ?",
        "ignore": "Ignorer",
        "pending_title": "Mesures Braun à attribuer",
        "pending_value": "{temperature} · {time}",
        "pending_line": "- {temperature}, le {time}",
        "pending_link": "[Ouvrir {device}](/config/devices/device/{device_id})",
    },
}


def _language(hass: HomeAssistant) -> str:
    return "fr" if hass.config.language.startswith("fr") else "en"


def text(hass: HomeAssistant, key: str, record: dict[str, Any] | None = None, **values: str) -> str:
    """Return a text in the server language, filled with a record's temperature and time."""
    if record is not None:
        temperature = f"{record.get('temperature')} °C"
        if _language(hass) == "fr":
            temperature = temperature.replace(".", ",")
        values["temperature"] = temperature
        values["time"] = ""
        if timestamp := record.get("timestamp"):
            values["time"] = dt_util.as_local(datetime.fromisoformat(timestamp)).strftime("%d/%m %H:%M")
    return TEXTS[_language(hass)][key].format(**values)
