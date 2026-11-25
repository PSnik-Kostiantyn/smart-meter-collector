"""Перевірка повідомлень від лічильників.

Кожне повідомлення проходить кроки у такому порядку.
1. Розбір JSON.
2. Перевірка схеми, тобто наявності й типів полів.
3. Відповідність номера лічильника в топіку і в тілі повідомлення.
4. Наявність лічильника в довіднику і збіг району.
5. Фізично можливі діапазони значень.
6. Узгодженість потужності з напругою і струмом.
7. Час вимірювання не з майбутнього і не надто старий.
8. Порядок повідомлень і монотонність накопиченого показника.

Діапазони взято з документації на PZEM-004T v3.0 із запасом
для трифазних лічильників і симуляції.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError

from .models import Meter, Reading, Rejected
from .registry import MeterRegistry

# (мінімум, максимум) для кожного поля
LIMITS: dict[str, tuple[float, float]] = {
    "voltage_v": (80.0, 300.0),
    "current_a": (0.0, 100.0),
    "power_w": (0.0, 69000.0),
    "energy_kwh": (0.0, 1e9),
    "frequency_hz": (45.0, 65.0),
    "power_factor": (0.0, 1.0),
}

# Допуск для перевірки P <= U * I * фази. Покриває похибку вимірювань.
POWER_TOLERANCE = 1.10
POWER_ABS_SLACK_W = 10.0
# Допустиме зменшення лічильника енергії через округлення на пристрої.
ENERGY_EPSILON_KWH = 0.001


class Reason:
    INVALID_JSON = "invalid_json"
    SCHEMA_ERROR = "schema_error"
    TOPIC_MISMATCH = "topic_mismatch"
    UNKNOWN_METER = "unknown_meter"
    DISTRICT_MISMATCH = "district_mismatch"
    OUT_OF_RANGE = "out_of_range"
    INCONSISTENT_POWER = "inconsistent_power"
    FUTURE_TIMESTAMP = "future_timestamp"
    STALE_TIMESTAMP = "stale_timestamp"
    OUT_OF_ORDER = "out_of_order"
    ENERGY_DECREASED = "energy_decreased"


@dataclass(frozen=True)
class Accepted:
    reading: Reading
    meter: Meter


@dataclass
class MeterState:
    last_ts: datetime
    last_energy_kwh: float


def parse_topic(topic: str) -> tuple[str, str] | None:
    """meters/<district>/<meter_id>/readings -> (district, meter_id)."""
    parts = topic.split("/")
    if parts and parts[0].startswith("$share"):
        parts = parts[2:]
    if len(parts) != 4 or parts[0] != "meters" or parts[3] != "readings":
        return None
    return parts[1], parts[2]


class Validator:
    def __init__(
        self,
        registry: MeterRegistry,
        max_clock_skew_s: float = 60.0,
        max_age_s: float = 7 * 24 * 3600,
    ):
        self.registry = registry
        self.max_clock_skew_s = max_clock_skew_s
        self.max_age_s = max_age_s
        self.state: dict[str, MeterState] = {}

    def seed_state(self, meter_id: str, last_ts: datetime, last_energy_kwh: float) -> None:
        """Відновлює останній відомий стан лічильника, наприклад із БД після перезапуску."""
        self.state[meter_id] = MeterState(last_ts, last_energy_kwh)

    def validate(
        self, topic: str, payload: bytes | str, now: datetime | None = None
    ) -> Accepted | Rejected:
        now = now or datetime.now(timezone.utc)
        raw = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload

        def reject(reason: str, detail: str = "", meter_id: str | None = None) -> Rejected:
            return Rejected(now, topic, raw, reason, detail, meter_id)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return reject(Reason.INVALID_JSON, str(exc))
        if not isinstance(data, dict):
            return reject(Reason.INVALID_JSON, "payload is not a JSON object")

        try:
            reading = Reading.model_validate(data)
        except ValidationError as exc:
            fields = ",".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
            return reject(Reason.SCHEMA_ERROR, fields, data.get("meter_id") if isinstance(data.get("meter_id"), str) else None)

        mid = reading.meter_id
        parsed = parse_topic(topic)
        if parsed is None or parsed[1] != mid:
            return reject(Reason.TOPIC_MISMATCH, f"topic={topic}", mid)
        topic_district = parsed[0]

        meter = self.registry.get(mid)
        if meter is None:
            return reject(Reason.UNKNOWN_METER, "", mid)
        if meter.district != topic_district:
            return reject(
                Reason.DISTRICT_MISMATCH, f"topic={topic_district} registry={meter.district}", mid
            )

        for field, (lo, hi) in LIMITS.items():
            value = getattr(reading, field)
            if not (lo <= value <= hi):  # також відсікає NaN
                return reject(Reason.OUT_OF_RANGE, f"{field}={value}", mid)

        apparent = reading.voltage_v * reading.current_a * max(meter.phase_type, 1)
        if reading.power_w > apparent * POWER_TOLERANCE + POWER_ABS_SLACK_W:
            return reject(
                Reason.INCONSISTENT_POWER,
                f"power_w={reading.power_w} > U*I={apparent:.1f}",
                mid,
            )

        age = (now - reading.ts).total_seconds()
        if age < -self.max_clock_skew_s:
            return reject(Reason.FUTURE_TIMESTAMP, reading.ts.isoformat(), mid)
        if age > self.max_age_s:
            return reject(Reason.STALE_TIMESTAMP, reading.ts.isoformat(), mid)

        prev = self.state.get(mid)
        if prev is not None:
            if reading.ts <= prev.last_ts:
                return reject(
                    Reason.OUT_OF_ORDER,
                    f"ts={reading.ts.isoformat()} last={prev.last_ts.isoformat()}",
                    mid,
                )
            if reading.energy_kwh + ENERGY_EPSILON_KWH < prev.last_energy_kwh:
                return reject(
                    Reason.ENERGY_DECREASED,
                    f"energy={reading.energy_kwh} last={prev.last_energy_kwh}",
                    mid,
                )

        self.state[mid] = MeterState(reading.ts, max(reading.energy_kwh, prev.last_energy_kwh if prev else 0.0))
        return Accepted(reading, meter)
