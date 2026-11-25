"""Лічильники прийнятих і відкинутих повідомлень та швидкість обробки."""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field

from .storage import MEASUREMENT_STATS


@dataclass
class Snapshot:
    interval_s: float
    received: int
    accepted: int
    rejected: int
    received_rate: float
    accepted_rate: float
    rejected_rate: float
    buffer: int
    by_reason: dict[str, int]


@dataclass
class Stats:
    received: int = 0
    accepted: int = 0
    rejected: int = 0
    by_reason: Counter = field(default_factory=Counter)
    _prev: tuple[float, int, int, int] = field(default_factory=lambda: (time.monotonic(), 0, 0, 0))

    def on_accepted(self) -> None:
        self.received += 1
        self.accepted += 1

    def on_rejected(self, reason: str) -> None:
        self.received += 1
        self.rejected += 1
        self.by_reason[reason] += 1

    def snapshot(self, buffer: int = 0) -> Snapshot:
        now = time.monotonic()
        t0, r0, a0, j0 = self._prev
        dt = max(now - t0, 1e-9)
        snap = Snapshot(
            interval_s=dt,
            received=self.received,
            accepted=self.accepted,
            rejected=self.rejected,
            received_rate=(self.received - r0) / dt,
            accepted_rate=(self.accepted - a0) / dt,
            rejected_rate=(self.rejected - j0) / dt,
            buffer=buffer,
            by_reason=dict(self.by_reason),
        )
        self._prev = (now, self.received, self.accepted, self.rejected)
        return snap


def snapshot_to_line(snap: Snapshot, instance: str, ts_ms: int) -> str:
    fields = (
        f"received={snap.received}i,accepted={snap.accepted}i,rejected={snap.rejected}i,"
        f"received_rate={snap.received_rate:.2f},accepted_rate={snap.accepted_rate:.2f},"
        f"rejected_rate={snap.rejected_rate:.2f},buffer={snap.buffer}i"
    )
    return f"{MEASUREMENT_STATS},instance={instance} {fields} {ts_ms}"
