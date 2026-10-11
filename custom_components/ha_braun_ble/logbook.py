"""Describe Braun events in the device activity log."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import DOMAIN, EVENT_BRAUN_ATTRIBUTION, EVENT_BRAUN_IGNORED, EVENT_BRAUN_MEASUREMENT
from .messages import text


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, str]]], None],
) -> None:
    """Describe the measurement, attribution and ignore events."""

    @callback
    def describe(event: Event) -> dict[str, str]:
        data = event.data
        name = data.get("person") if event.event_type == EVENT_BRAUN_ATTRIBUTION else data.get("device_name")
        return {
            LOGBOOK_ENTRY_NAME: name or "Braun",
            LOGBOOK_ENTRY_MESSAGE: text(hass, event.event_type, dict(data)),
        }

    for event_type in (EVENT_BRAUN_MEASUREMENT, EVENT_BRAUN_ATTRIBUTION, EVENT_BRAUN_IGNORED):
        async_describe_event(DOMAIN, event_type, describe)
