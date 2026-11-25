"""Налаштування колектора. Усі значення читаються зі змінних оточення."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = _env("MQTT_HOST", "localhost")
    mqtt_port: int = int(_env("MQTT_PORT", "1883"))
    mqtt_username: str | None = os.environ.get("MQTT_USERNAME") or None
    mqtt_password: str | None = os.environ.get("MQTT_PASSWORD") or None
    # Спільна підписка дозволяє запустити кілька копій колектора,
    # і брокер розподілить повідомлення між ними.
    mqtt_topic: str = _env("MQTT_TOPIC", "$share/collectors/meters/+/+/readings")
    mqtt_qos: int = int(_env("MQTT_QOS", "1"))
    mqtt_client_id: str = _env("MQTT_CLIENT_ID", "")

    influx_url: str = _env("INFLUX_URL", "http://localhost:8086")
    influx_token: str = _env("INFLUX_TOKEN", "dev-token")
    influx_org: str = _env("INFLUX_ORG", "iot")
    influx_bucket: str = _env("INFLUX_BUCKET", "meters")

    meters_file: str = _env("METERS_FILE", "config/meters.json")
    batch_size: int = int(_env("BATCH_SIZE", "1000"))
    flush_interval_s: float = float(_env("FLUSH_INTERVAL_S", "1.0"))
    stats_interval_s: float = float(_env("STATS_INTERVAL_S", "5.0"))
    max_clock_skew_s: float = float(_env("MAX_CLOCK_SKEW_S", "60"))
    max_age_s: float = float(_env("MAX_AGE_S", str(7 * 24 * 3600)))
    log_level: str = _env("LOG_LEVEL", "INFO")
