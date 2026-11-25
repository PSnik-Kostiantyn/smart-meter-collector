"""Точка входу колектора.

Колектор підписується на топіки meters/+/+/readings, перевіряє кожне
повідомлення і пачками пише прийняті показники та відкинуті повідомлення
в InfluxDB. Раз на STATS_INTERVAL_S секунд він пише в журнал і в БД
кількість прийнятих та відкинутих повідомлень.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import socket
import time
import uuid

import aiomqtt

from .config import Settings
from .registry import MeterRegistry
from .stats import Stats, snapshot_to_line
from .storage import BatchWriter, InfluxSink, Sink, reading_to_line, rejected_to_line
from .validator import Accepted, Validator

log = logging.getLogger("collector")


class Collector:
    """Логіка обробки без прив'язки до мережі. Її зручно тестувати окремо."""

    def __init__(self, validator: Validator, writer: BatchWriter, stats: Stats | None = None):
        self.validator = validator
        self.writer = writer
        self.stats = stats or Stats()

    def handle(self, topic: str, payload: bytes) -> bool:
        result = self.validator.validate(topic, payload)
        if isinstance(result, Accepted):
            self.writer.add(reading_to_line(result))
            self.stats.on_accepted()
            return True
        self.writer.add(rejected_to_line(result))
        self.stats.on_rejected(result.reason)
        log.debug("rejected %s from %s: %s", result.reason, topic, result.detail)
        return False


async def _flush_loop(writer: BatchWriter, stop: asyncio.Event) -> None:
    while not stop.is_set():
        if writer.should_flush():
            await writer.flush()
        await asyncio.sleep(0.05)


async def _stats_loop(collector: Collector, settings: Settings, instance: str, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.stats_interval_s)
        except asyncio.TimeoutError:
            pass
        snap = collector.stats.snapshot(buffer=len(collector.writer))
        log.info(
            "received=%d accepted=%d rejected=%d | %.0f msg/s in, %.0f ok/s, %.0f bad/s | buffer=%d written=%d",
            snap.received, snap.accepted, snap.rejected,
            snap.received_rate, snap.accepted_rate, snap.rejected_rate,
            snap.buffer, collector.writer.written,
        )
        if snap.by_reason:
            log.info("rejected by reason: %s", snap.by_reason)
        collector.writer.add(snapshot_to_line(snap, instance, time.time_ns()))


async def _registry_loop(registry: MeterRegistry, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=10)
        except asyncio.TimeoutError:
            registry.reload_if_changed()


async def _mqtt_loop(collector: Collector, settings: Settings, client_id: str, stop: asyncio.Event) -> None:
    backoff = 1.0
    while not stop.is_set():
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                identifier=client_id,
                username=settings.mqtt_username,
                password=settings.mqtt_password,
            ) as client:
                await client.subscribe(settings.mqtt_topic, qos=settings.mqtt_qos)
                log.info("subscribed to %s on %s:%d", settings.mqtt_topic, settings.mqtt_host, settings.mqtt_port)
                backoff = 1.0
                async for message in client.messages:
                    collector.handle(str(message.topic), message.payload)
                    if collector.writer.should_flush() and len(collector.writer) >= collector.writer.batch_size:
                        await collector.writer.flush()
                    if stop.is_set():
                        break
        except aiomqtt.MqttError as exc:
            log.warning("MQTT connection lost (%s), reconnect in %.0f s", exc, backoff)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 30.0)


async def run(settings: Settings) -> None:
    registry = MeterRegistry(settings.meters_file)
    validator = Validator(registry, settings.max_clock_skew_s, settings.max_age_s)
    sink = InfluxSink(settings.influx_url, settings.influx_token, settings.influx_org, settings.influx_bucket)
    writer = BatchWriter(sink, settings.batch_size, settings.flush_interval_s)
    collector = Collector(validator, writer)

    try:
        state = await sink.load_last_state()
        for meter_id, (ts, energy) in state.items():
            validator.seed_state(meter_id, ts, energy)
        log.info("restored last state for %d meters", len(state))
    except Exception as exc:
        log.warning("could not restore state from InfluxDB: %s", exc)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    client_id = settings.mqtt_client_id or f"collector-{socket.gethostname()}-{uuid.uuid4().hex[:6]}"
    tasks = [
        asyncio.create_task(_mqtt_loop(collector, settings, client_id, stop)),
        asyncio.create_task(_flush_loop(writer, stop)),
        asyncio.create_task(_stats_loop(collector, settings, client_id, stop)),
        asyncio.create_task(_registry_loop(registry, stop)),
    ]
    await stop.wait()
    log.info("stopping, flushing %d buffered points", len(writer))
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await writer.flush()
    await sink.close()


def main() -> None:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
