"""Measurement kinds: what a device measures and how it is shown, independent of its protocol."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.util.unit_conversion import TemperatureConverter


@dataclass(frozen=True, kw_only=True)
class BraunSensorDescription(SensorEntityDescription):
    """Sensor reading one field of the latest record."""

    # Also show the latest record's time and details as attributes.
    record_attributes: bool = False


@dataclass(frozen=True)
class Statistic:
    """Long-term statistic written at the real measurement time for each person."""

    field: str
    unit: str
    unit_class: str | None
    name_suffix: str = ""


@dataclass(frozen=True)
class MeasurementKind:
    """Fields, entities and texts for one kind of measurement."""

    key: str
    # Fields a record must carry to count as a measurement.
    value_fields: tuple[str, ...]
    # Extra record fields shown as attributes.
    attributes: tuple[str, ...]
    device_sensors: tuple[BraunSensorDescription, ...]
    person_sensors: tuple[SensorEntityDescription, ...]
    statistics: tuple[Statistic, ...]
    # Short text for a record, such as "36,7 °C", in the given language.
    format_value: Callable[[dict[str, Any], str], str]
    # Optional context added to notifications, such as the age profile.
    format_details: Callable[[dict[str, Any], str], str] = lambda _record, _language: ""

    def is_measurement(self, record: dict[str, Any]) -> bool:
        """Return whether a record carries every value field."""
        return all(field in record for field in self.value_fields)


def _format_temperature(record: dict[str, Any], language: str) -> str:
    text = f"{record.get('temperature')} °C"
    return text.replace(".", ",") if language == "fr" else text


AGE_PROFILE_LABELS = {
    "en": {"0_3_months": "0-3 months", "3_36_months": "3-36 months", "over_36_months": "over 36 months"},
    "fr": {"0_3_months": "0-3 mois", "3_36_months": "3-36 mois", "over_36_months": "plus de 36 mois"},
}


def _format_age_profile(record: dict[str, Any], language: str) -> str:
    label = AGE_PROFILE_LABELS[language].get(record.get("age_profile") or "")
    if not label:
        return ""
    return f" (profil {label})" if language == "fr" else f" ({label} profile)"


TEMPERATURE = MeasurementKind(
    key="temperature",
    value_fields=("temperature",),
    attributes=("ambient_temperature", "age_profile"),
    device_sensors=(
        BraunSensorDescription(
            key="temperature",
            translation_key="temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            icon="mdi:thermometer",
            record_attributes=True,
        ),
        BraunSensorDescription(
            key="ambient_temperature",
            translation_key="ambient_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            entity_registry_enabled_default=False,
        ),
    ),
    person_sensors=(
        SensorEntityDescription(
            key="temperature",
            translation_key="person_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        ),
    ),
    statistics=(
        Statistic("temperature", UnitOfTemperature.CELSIUS, TemperatureConverter.UNIT_CLASS),
    ),
    format_value=_format_temperature,
    format_details=_format_age_profile,
)

KINDS = {kind.key: kind for kind in (TEMPERATURE,)}

# Device sensors every model has, whatever it measures.
BATTERY = SensorEntityDescription(
    key="battery",
    translation_key="battery",
    device_class=SensorDeviceClass.BATTERY,
    state_class=SensorStateClass.MEASUREMENT,
    native_unit_of_measurement=PERCENTAGE,
)
MODEL_NUMBER = SensorEntityDescription(
    key="model_number",
    translation_key="model_number",
    entity_category=EntityCategory.DIAGNOSTIC,
)
FIRMWARE = SensorEntityDescription(
    key="firmware",
    translation_key="firmware",
    entity_category=EntityCategory.DIAGNOSTIC,
)
COMMON_SENSORS = (BATTERY, MODEL_NUMBER, FIRMWARE)
