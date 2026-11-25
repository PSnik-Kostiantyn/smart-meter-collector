"""Довідник лічильників. Зберігається у JSON-файлі й перечитується, коли файл змінюється."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .models import Meter

log = logging.getLogger(__name__)


class MeterRegistry:
    def __init__(self, path: str | os.PathLike | None = None, meters: list[Meter] | None = None):
        self._path = Path(path) if path else None
        self._mtime: float | None = None
        self._meters: dict[str, Meter] = {m.meter_id: m for m in (meters or [])}
        if self._path:
            self.reload_if_changed()

    def __len__(self) -> int:
        return len(self._meters)

    def get(self, meter_id: str) -> Meter | None:
        return self._meters.get(meter_id)

    def reload_if_changed(self) -> bool:
        """Перечитує файл, якщо він змінився. Повертає True, коли довідник оновлено."""
        if not self._path:
            return False
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            log.warning("meters file %s not found, registry is empty", self._path)
            return False
        if mtime == self._mtime:
            return False
        with self._path.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        meters = {}
        for item in raw:
            meter = Meter(
                meter_id=item["meter_id"],
                district=item["district"],
                phase_type=int(item.get("phase_type", 1)),
                customer_type=item.get("customer_type", "household"),
                installed_at=item.get("installed_at"),
            )
            meters[meter.meter_id] = meter
        self._meters = meters
        self._mtime = mtime
        log.info("loaded %d meters from %s", len(meters), self._path)
        return True
