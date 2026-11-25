"""Звіряє кількість записаного в InfluxDB із підсумком емулятора.

Приклад
    python tools/verify_counts.py --report results/run.json --since -1h
"""

from __future__ import annotations

import argparse
import json
from collections import Counter

from influxdb_client import InfluxDBClient


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8086")
    ap.add_argument("--token", default="dev-token-change-me")
    ap.add_argument("--org", default="iot")
    ap.add_argument("--bucket", default="meters")
    ap.add_argument("--start", default="-30d", help="початок діапазону для readings, час вимірювання")
    ap.add_argument("--since", default="-1h", help="початок діапазону для rejected_messages, час отримання")
    ap.add_argument("--report", default="", help="JSON-підсумок від fake_meters.py")
    args = ap.parse_args()

    with InfluxDBClient(url=args.url, token=args.token, org=args.org, timeout=120_000) as client:
        q = client.query_api()
        readings = 0
        for t in q.query(f'''
from(bucket: "{args.bucket}") |> range(start: {args.start}, stop: 2d)
  |> filter(fn: (r) => r._measurement == "readings" and r._field == "energy_kwh")
  |> group() |> count()'''):
            for r in t.records:
                readings += int(r.get_value())
        rejected = Counter()
        for t in q.query(f'''
from(bucket: "{args.bucket}") |> range(start: {args.since}, stop: 2d)
  |> filter(fn: (r) => r._measurement == "rejected_messages" and r._field == "topic")
  |> group(columns: ["reason"]) |> count()'''):
            for r in t.records:
                rejected[r.values["reason"]] += int(r.get_value())

    result = {"readings_in_db": readings, "rejected_in_db": sum(rejected.values()),
              "rejected_by_reason": dict(rejected)}
    if args.report:
        with open(args.report, encoding="utf-8") as fh:
            sent = json.load(fh)
        ok_sent = sent["by_kind"].get("ok", 0)
        bad_sent = sent["sent"] - ok_sent
        result["sent_ok"] = ok_sent
        result["sent_bad"] = bad_sent
        result["lost_ok"] = ok_sent - readings
        result["lost_bad"] = bad_sent - result["rejected_in_db"]
        result["bad_by_kind_sent"] = {k: v for k, v in sent["by_kind"].items() if k != "ok"}
    print(json.dumps(result, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
