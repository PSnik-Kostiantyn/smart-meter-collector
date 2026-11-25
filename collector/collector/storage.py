"""Пакетний запис у InfluxDB.

Точки формуються одразу у line protocol, бо так менше накладних витрат,
ніж через об'єкти Point. Буфер скидається, коли набирається batch_size
точок або минає flush_interval секунд.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections import deque
from datetime import datetime
from typing import Protocol

from .models import Rejected
from .validator import Accepted

log = logging.getLogger(__name__)

MEASUREMENT_READINGS = "readings"
MEASUREMENT_REJECTED = "rejected_messages"
MEASUREMENT_STATS = "collector_stats"

# Обмеження буфера на випадок, якщо БД довго недоступна.
MAX_BUFFER = 200_000


def _esc_tag(value: str) -> str:
    return value.replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def _esc_str(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _ns(ts: datetime) -> int:
    return int(ts.timestamp() * 1_000_000) * 1000


# InfluxDB вважає точки з однаковими measurement, тегами й часом однією точкою
# і перезаписує попередню. Відкинуті повідомлення без номера лічильника,
# отримані в одну мілісекунду, інакше зливалися б, тому до їхнього часу
# додається порядковий номер у наносекундах.
_seq = itertools.count()


def reading_to_line(acc: Accepted) -> str:
    r, m = acc.reading, acc.meter
    tags = (
        f"meter_id={_esc_tag(r.meter_id)},district={_esc_tag(m.district)},"
        f"customer_type={_esc_tag(m.customer_type)}"
    )
    fields = (
        f"energy_kwh={r.energy_kwh},power_w={r.power_w},voltage_v={r.voltage_v},"
        f"current_a={r.current_a},power_factor={r.power_factor},frequency_hz={r.frequency_hz}"
    )
    return f"{MEASUREMENT_READINGS},{tags} {fields} {_ns(r.ts)}"


def rejected_to_line(rej: Rejected) -> str:
    tags = f"reason={_esc_tag(rej.reason)}"
    if rej.meter_id:
        tags += f",meter_id={_esc_tag(rej.meter_id)}"
    payload = rej.raw_payload[:4096]
    fields = (
        f'raw_payload="{_esc_str(payload)}",topic="{_esc_str(rej.topic)}",'
        f'detail="{_esc_str(rej.detail[:512])}"'
    )
    return f"{MEASUREMENT_REJECTED},{tags} {fields} {_ns(rej.received_at) + next(_seq) % 1_000_000}"


class Sink(Protocol):
    async def write(self, lines: list[str]) -> None: ...


class InfluxSink:
    def __init__(self, url: str, token: str, org: str, bucket: str):
        from influxdb_client import WritePrecision
        from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

        self._precision = WritePrecision.NS
        self._client = InfluxDBClientAsync(url=url, token=token, org=org, timeout=30_000)
        self._write_api = self._client.write_api()
        self._org = org
        self.bucket = bucket

    async def write(self, lines: list[str]) -> None:
        await self._write_api.write(
            bucket=self.bucket, org=self._org, record=lines, write_precision=self._precision
        )

    async def load_last_state(self, days: int = 30) -> dict[str, tuple[datetime, float]]:
        """Останні час і показник енергії кожного лічильника, щоб після перезапуску
        не пропустити зменшення показника."""
        flux = f'''
from(bucket: "{self.bucket}")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r._measurement == "{MEASUREMENT_READINGS}" and r._field == "energy_kwh")
  |> group(columns: ["meter_id"])
  |> last()
'''
        result: dict[str, tuple[datetime, float]] = {}
        tables = await self._client.query_api().query(flux, org=self._org)
        for table in tables:
            for rec in table.records:
                result[rec.values["meter_id"]] = (rec.get_time(), float(rec.get_value()))
        return result

    async def close(self) -> None:
        await self._client.close()


class BatchWriter:
    def __init__(self, sink: Sink, batch_size: int = 1000, flush_interval_s: float = 1.0):
        self.sink = sink
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self._buf: deque[str] = deque()
        self._last_flush = time.monotonic()
        self._lock = asyncio.Lock()
        self.written = 0
        self.dropped = 0
        self.write_errors = 0
        self.flushes = 0

    def __len__(self) -> int:
        return len(self._buf)

    def add(self, line: str) -> None:
        if len(self._buf) >= MAX_BUFFER:
            self._buf.popleft()
            self.dropped += 1
        self._buf.append(line)

    def should_flush(self) -> bool:
        if not self._buf:
            return False
        return (
            len(self._buf) >= self.batch_size
            or time.monotonic() - self._last_flush >= self.flush_interval_s
        )

    async def flush(self) -> int:
        """Записує одну або кілька пачок. Якщо запис не вдався, точки лишаються в буфері."""
        async with self._lock:
            total = 0
            while self._buf:
                n = min(self.batch_size, len(self._buf))
                batch = [self._buf[i] for i in range(n)]
                try:
                    await self.sink.write(batch)
                except Exception as exc:  # мережа, 5xx від InfluxDB тощо
                    self.write_errors += 1
                    log.warning("write of %d points failed: %s", n, exc)
                    break
                for _ in range(n):
                    self._buf.popleft()
                total += n
                self.flushes += 1
            self.written += total
            self._last_flush = time.monotonic()
            return total
