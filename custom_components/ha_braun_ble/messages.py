"""Texts the integration writes itself: activity log, notifications, pending sensor.

Home Assistant only translates entity and flow strings, so these follow the server language.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import EVENT_BRAUN_ATTRIBUTION, EVENT_BRAUN_IGNORED, EVENT_BRAUN_MEASUREMENT
from .kinds import KINDS

TEXTS = {
    "en": {
        EVENT_BRAUN_MEASUREMENT: "measured {value}{details}",
        EVENT_BRAUN_ATTRIBUTION: "was attributed {value}, measured {time}",
        EVENT_BRAUN_IGNORED: "ignored the {value} measurement from {time}",
        "notify_message": "{value} measured {time}{details}. Who was it for?",
        "ignore": "Ignore",
        "pending_title": "Braun measurements to attribute",
        "no_pending": "None",
        "pending_value": "{value} · {time}",
        "pending_line": "- {value}, {time}",
        "pending_link": "[Open {device}](/config/devices/device/{device_id})",
    },
    "fr": {
        EVENT_BRAUN_MEASUREMENT: "a mesuré {value}{details}",
        EVENT_BRAUN_ATTRIBUTION: "s'est vu attribuer {value}, mesurés le {time}",
        EVENT_BRAUN_IGNORED: "a ignoré la mesure de {value} du {time}",
        "notify_message": "{value} mesurés le {time}{details}. Pour qui ?",
        "ignore": "Ignorer",
        "pending_title": "Mesures Braun à attribuer",
        "no_pending": "Aucune",
        "pending_value": "{value} · {time}",
        "pending_line": "- {value}, le {time}",
        "pending_link": "[Ouvrir {device}](/config/devices/device/{device_id})",
    },
}


def _language(hass: HomeAssistant) -> str:
    return "fr" if hass.config.language.startswith("fr") else "en"


def text(hass: HomeAssistant, key: str, record: dict[str, Any] | None = None, **values: str) -> str:
    """Return a text in the server language, filled with a record's value and time."""
    if record is not None:
        # Records stored before kinds existed are temperatures.
        kind = KINDS[record.get("kind", "temperature")]
        values["value"] = kind.format_value(record, _language(hass))
        values["details"] = kind.format_details(record, _language(hass))
        values["time"] = ""
        if timestamp := record.get("timestamp"):
            # Day first in French; English spells the month out to stay unambiguous.
            fmt = "%d/%m %H:%M" if _language(hass) == "fr" else "%b %d %H:%M"
            values["time"] = dt_util.as_local(datetime.fromisoformat(timestamp)).strftime(fmt)
    return TEXTS[_language(hass)][key].format(**values)
