"""Простий емулятор лічильників для перевірки колектора.

Повноцінна симуляція навантаження належить до частини 1.3. Цей скрипт
потрібен, щоб перевірити колектор, тому вміє навмисно псувати частину
повідомлень і показує, скільки яких дефектів він надіслав.

Приклади
    # 1000 лічильників, кожен раз на секунду, 5% зіпсованих, 60 секунд
    python tools/fake_meters.py --meters config/meters.json --interval 1 --duration 60 --bad 0.05

    # надіслати рівно 200000 повідомлень якнайшвидше
    python tools/fake_meters.py --meters config/meters.json --total 200000 --rate 0
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt

DEFECTS = [
    "invalid_json", "schema_error", "topic_mismatch", "unknown_meter", "out_of_range",
    "inconsistent_power", "future_timestamp", "energy_decreased",
]


@dataclass
class MeterSim:
    meter_id: str
    district: str
    phases: int
    base_w: float
    energy_kwh: float
    last_ts: datetime | None = None

    def next_reading(self, ts: datetime, rnd: random.Random) -> dict:
        hour = ts.hour + ts.minute / 60
        # добовий профіль із ранковим і вечірнім піком
        profile = 0.35 + 0.4 * math.exp(-((hour - 8) ** 2) / 4) + 0.8 * math.exp(-((hour - 20) ** 2) / 6)
        power = max(0.0, self.base_w * profile * rnd.uniform(0.8, 1.2))
        voltage = rnd.gauss(230.0, 3.0)
        pf = min(1.0, max(0.5, rnd.gauss(0.93, 0.03)))
        current = power / (voltage * pf * self.phases) if power else 0.0
        if self.last_ts is not None:
            dt_h = max((ts - self.last_ts).total_seconds(), 0) / 3600
            self.energy_kwh += power * dt_h / 1000
        self.last_ts = ts
        return {
            "meter_id": self.meter_id,
            "ts": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "energy_kwh": round(self.energy_kwh, 3),
            "power_w": round(power, 1),
            "voltage_v": round(voltage, 1),
            "current_a": round(current, 3),
            "power_factor": round(pf, 2),
            "frequency_hz": round(rnd.gauss(50.0, 0.02), 2),
        }


def corrupt(kind: str, topic: str, msg: dict, rnd: random.Random) -> tuple[str, str]:
    m = dict(msg)
    if kind == "invalid_json":
        return topic, json.dumps(m)[:-5]
    if kind == "schema_error":
        m.pop(rnd.choice(["voltage_v", "energy_kwh", "ts", "current_a"]))
    elif kind == "topic_mismatch":
        m["meter_id"] = "M-999999"
        return topic, json.dumps(m)
    elif kind == "unknown_meter":
        m["meter_id"] = f"X-{rnd.randint(0, 99999):05d}"
        parts = topic.split("/")
        topic = f"{parts[0]}/{parts[1]}/{m['meter_id']}/{parts[3]}"
    elif kind == "out_of_range":
        m["voltage_v"] = rnd.choice([0.0, 512.0, -230.0])
    elif kind == "inconsistent_power":
        m["power_w"] = round(m["voltage_v"] * m["current_a"] * 6 + 1000, 1)
    elif kind == "future_timestamp":
        ts = datetime.now(timezone.utc) + timedelta(hours=2)
        m["ts"] = ts.isoformat().replace("+00:00", "Z")
    elif kind == "energy_decreased":
        m["energy_kwh"] = max(0.0, m["energy_kwh"] - 50)
    return topic, json.dumps(m)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--meters", default="config/meters.json")
    ap.add_argument("--offset", type=int, default=0, help="пропустити перші N лічильників довідника")
    ap.add_argument("--limit", type=int, default=0, help="використати лише N лічильників")
    ap.add_argument("--interval", type=float, default=1.0, help="секунд між повідомленнями одного лічильника")
    ap.add_argument("--duration", type=float, default=0, help="тривалість у секундах, 0 означає без обмеження")
    ap.add_argument("--total", type=int, default=0, help="зупинитися після N повідомлень")
    ap.add_argument("--rate", type=float, default=-1,
                    help="загальна швидкість, повідомлень за секунду. 0 означає без обмеження, -1 означає з --interval")
    ap.add_argument("--bad", type=float, default=0.0, help="частка зіпсованих повідомлень, від 0 до 1")
    ap.add_argument("--qos", type=int, default=1)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--report", default="", help="записати підсумок у JSON-файл")
    args = ap.parse_args()

    rnd = random.Random(args.seed)
    with open(args.meters, encoding="utf-8") as fh:
        registry = json.load(fh)
    registry = registry[args.offset:]
    if args.limit:
        registry = registry[: args.limit]
    sims = [
        MeterSim(m["meter_id"], m["district"], int(m.get("phase_type", 1)),
                 base_w={"household": 900, "commercial": 6000, "industrial": 25000}[m.get("customer_type", "household")]
                 * rnd.uniform(0.6, 1.4),
                 energy_kwh=rnd.uniform(100, 9000))
        for m in registry
    ]

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"fake-meters-{os.getpid()}-{args.offset}")
    client.max_inflight_messages_set(1000)
    client.max_queued_messages_set(0)
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()

    rate = args.rate if args.rate >= 0 else len(sims) / args.interval
    sent = Counter()
    start = time.monotonic()
    # Віртуальний час. Кожне коло по всіх лічильниках відповідає одному інтервалу.
    vt = datetime.now(timezone.utc) - timedelta(seconds=args.interval)
    if args.rate == 0 or args.total:
        vt = datetime.now(timezone.utc) - timedelta(hours=6)
    n = 0
    last_info = start
    infos = []
    try:
        while True:
            for sim in sims:
                msg = sim.next_reading(vt, rnd)
                topic = f"meters/{sim.district}/{sim.meter_id}/readings"
                kind = "ok"
                if args.bad and rnd.random() < args.bad:
                    kind = rnd.choice(DEFECTS)
                    topic, payload = corrupt(kind, topic, msg, rnd)
                else:
                    payload = json.dumps(msg)
                info = client.publish(topic, payload, qos=args.qos)
                if args.qos:
                    infos.append(info)
                    if len(infos) >= 5000:
                        for i in infos:
                            i.wait_for_publish(timeout=30)
                        infos.clear()
                sent[kind] += 1
                n += 1
                if rate > 0:
                    target = start + n / rate
                    delay = target - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                now = time.monotonic()
                if now - last_info >= 5:
                    print(f"sent {n} messages, {n / (now - start):.0f} msg/s")
                    last_info = now
                if (args.total and n >= args.total) or (args.duration and now - start >= args.duration):
                    raise StopIteration
            vt += timedelta(seconds=args.interval if args.rate != 0 and not args.total else 1)
    except (StopIteration, KeyboardInterrupt):
        pass
    for i in infos:
        i.wait_for_publish(timeout=30)
    elapsed = time.monotonic() - start
    client.loop_stop()
    client.disconnect()
    summary = {"sent": n, "elapsed_s": round(elapsed, 2), "rate_msg_s": round(n / elapsed, 1),
               "by_kind": dict(sent), "meters": len(sims)}
    print(json.dumps(summary, indent=1))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1)


if __name__ == "__main__":
    main()
