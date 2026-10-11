"""Describe Braun events in the device activity log."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, EVENT_BRAUN_ATTRIBUTION, EVENT_BRAUN_IGNORED, EVENT_BRAUN_MEASUREMENT

# Logbook messages have no translation mechanism, so they follow the server language.
MESSAGES = {
    "en": {
        EVENT_BRAUN_MEASUREMENT: "measured {temperature} °C",
        EVENT_BRAUN_ATTRIBUTION: "was attributed {temperature} °C, measured {time}",
        EVENT_BRAUN_IGNORED: "ignored the {temperature} °C measurement from {time}",
    },
    "fr": {
        EVENT_BRAUN_MEASUREMENT: "a mesuré {temperature} °C",
        EVENT_BRAUN_ATTRIBUTION: "s'est vu attribuer {temperature} °C, mesurés le {time}",
        EVENT_BRAUN_IGNORED: "a ignoré la mesure de {temperature} °C du {time}",
    },
}


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe the measurement, attribution and ignore events."""
    messages = MESSAGES["fr" if hass.config.language.startswith("fr") else "en"]

    @callback
    def describe(event: Event) -> dict[str, str]:
        data = event.data
        temperature = f"{data.get('temperature')}"
        time = ""
        if timestamp := data.get("timestamp"):
            time = dt_util.as_local(datetime.fromisoformat(timestamp)).strftime("%d/%m %H:%M")
        if messages is MESSAGES["fr"]:
            temperature = temperature.replace(".", ",")
        name = data.get("person") if event.event_type == EVENT_BRAUN_ATTRIBUTION else data.get("device_name")
        return {
            LOGBOOK_ENTRY_NAME: name or "Braun",
            LOGBOOK_ENTRY_MESSAGE: messages[event.event_type].format(temperature=temperature, time=time),
        }

    for event_type in (EVENT_BRAUN_MEASUREMENT, EVENT_BRAUN_ATTRIBUTION, EVENT_BRAUN_IGNORED):
        async_describe_event(DOMAIN, event_type, describe)
