import asyncio
import json
from datetime import datetime, timezone

from collector.main import Collector
from collector.models import Meter, Rejected
from collector.registry import MeterRegistry
from collector.stats import Stats, snapshot_to_line
from collector.storage import BatchWriter, reading_to_line, rejected_to_line
from collector.validator import Validator


class FakeSink:
    def __init__(self, fail_times: int = 0):
        self.batches: list[list[str]] = []
        self.fail_times = fail_times

    async def write(self, lines):
        if self.fail_times:
            self.fail_times -= 1
            raise ConnectionError("influx down")
        self.batches.append(list(lines))


def run(coro):
    return asyncio.run(coro)


def test_reading_line_protocol():
    v = Validator(MeterRegistry(meters=[Meter("M 1", "obolon,skyi", 1, "household")]))
    payload = json.dumps({
        "meter_id": "M 1", "ts": "2026-11-23T11:59:00Z", "energy_kwh": 1.5, "power_w": 100.0,
        "voltage_v": 230.0, "current_a": 0.5, "power_factor": 0.9, "frequency_hz": 50.0,
    })
    acc = v.validate("meters/obolon,skyi/M 1/readings", payload,
                     now=datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc))
    line = reading_to_line(acc)
    assert line.startswith("readings,meter_id=M\\ 1,district=obolon\\,skyi,customer_type=household ")
    assert "energy_kwh=1.5,power_w=100.0" in line
    assert line.endswith(" 1795435140000000000")


def test_rejected_line_escapes_payload():
    rej = Rejected(datetime(2026, 11, 23, tzinfo=timezone.utc), "meters/a/b/readings",
                   '{"a": "x\\y"}\n', "invalid_json", "detail")
    line = rejected_to_line(rej)
    assert line.startswith("rejected_messages,reason=invalid_json ")
    assert 'raw_payload="{\\"a\\": \\"x\\\\y\\"}\\n"' in line


def test_rejected_lines_get_unique_timestamps():
    rej = Rejected(datetime(2026, 11, 23, tzinfo=timezone.utc), "t", "x", "invalid_json")
    stamps = {rejected_to_line(rej).rsplit(" ", 1)[1] for _ in range(1000)}
    assert len(stamps) == 1000


def test_batches_are_split_by_size():
    sink = FakeSink()
    w = BatchWriter(sink, batch_size=3, flush_interval_s=100)
    for i in range(7):
        w.add(f"m v={i}")
    assert w.should_flush()
    assert run(w.flush()) == 7
    assert [len(b) for b in sink.batches] == [3, 3, 1]
    assert len(w) == 0 and w.written == 7


def test_points_are_kept_when_write_fails():
    sink = FakeSink(fail_times=1)
    w = BatchWriter(sink, batch_size=10, flush_interval_s=0)
    for i in range(5):
        w.add(f"m v={i}")
    assert run(w.flush()) == 0
    assert len(w) == 5 and w.write_errors == 1
    assert run(w.flush()) == 5
    assert sink.batches == [[f"m v={i}" for i in range(5)]]


def test_collector_counts_and_routes_messages():
    reg = MeterRegistry(meters=[Meter("M-1", "d", 1)])
    sink = FakeSink()
    c = Collector(Validator(reg), BatchWriter(sink, batch_size=100, flush_interval_s=0))
    good = json.dumps({
        "meter_id": "M-1", "ts": datetime.now(timezone.utc).isoformat(), "energy_kwh": 1.0,
        "power_w": 10.0, "voltage_v": 230.0, "current_a": 0.1, "power_factor": 0.9, "frequency_hz": 50.0,
    }).encode()
    assert c.handle("meters/d/M-1/readings", good) is True
    assert c.handle("meters/d/M-1/readings", b"oops") is False
    assert (c.stats.received, c.stats.accepted, c.stats.rejected) == (2, 1, 1)
    assert c.stats.by_reason == {"invalid_json": 1}
    run(c.writer.flush())
    lines = sink.batches[0]
    assert lines[0].startswith("readings,") and lines[1].startswith("rejected_messages,")


def test_stats_snapshot_line():
    s = Stats()
    s.on_accepted()
    s.on_rejected("x")
    snap = s.snapshot(buffer=4)
    assert snap.received == 2 and snap.by_reason == {"x": 1}
    line = snapshot_to_line(snap, "c1", 1000)
    assert line.startswith("collector_stats,instance=c1 received=2i,accepted=1i,rejected=1i,")
    assert line.endswith(" 1000")
