"""Формат повідомлення від лічильника і структура відкинутого повідомлення."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Reading(BaseModel):
    """Одне вимірювання, яке лічильник публікує в MQTT.

    Поля відповідають тому, що повертає модуль PZEM-004T v3.0.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    meter_id: str = Field(min_length=1, max_length=64)
    ts: datetime
    energy_kwh: float
    power_w: float
    voltage_v: float
    current_a: float
    power_factor: float
    frequency_hz: float

    @field_validator("ts", mode="before")
    @classmethod
    def _parse_ts(cls, value):
        # Пристрій може надіслати Unix-час у секундах або рядок ISO 8601.
        if isinstance(value, bool):
            raise ValueError("ts must be ISO 8601 string or unix seconds")
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        return value

    @field_validator("ts")
    @classmethod
    def _require_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("ts must contain a timezone, e.g. 2026-11-23T00:15:00Z")
        return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Meter:
    """Запис довідника лічильників."""

    meter_id: str
    district: str
    phase_type: int = 1
    customer_type: str = "household"
    installed_at: str | None = None


@dataclass(frozen=True)
class Rejected:
    """Повідомлення, яке не пройшло перевірку."""

    received_at: datetime
    topic: str
    raw_payload: str
    reason: str
    detail: str = ""
    meter_id: str | None = None
