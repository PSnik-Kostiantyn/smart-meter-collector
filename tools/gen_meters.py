"""Генерує довідник лічильників config/meters.json.

Приклад
    python tools/gen_meters.py --count 1000 --out config/meters.json
"""

from __future__ import annotations

import argparse
import json
import random

DISTRICTS = ["holosiivskyi", "darnytskyi", "desnianskyi", "dniprovskyi", "obolonskyi",
             "pecherskyi", "podilskyi", "sviatoshynskyi", "solomianskyi", "shevchenkivskyi"]
CUSTOMER_TYPES = [("household", 0.85), ("commercial", 0.12), ("industrial", 0.03)]


def make_meters(count: int, seed: int = 42) -> list[dict]:
    rnd = random.Random(seed)
    meters = []
    for i in range(1, count + 1):
        ctype = rnd.choices([c for c, _ in CUSTOMER_TYPES], [w for _, w in CUSTOMER_TYPES])[0]
        meters.append({
            "meter_id": f"M-{i:06d}",
            "district": DISTRICTS[(i - 1) % len(DISTRICTS)],
            "phase_type": 1 if ctype == "household" else 3,
            "customer_type": ctype,
            "installed_at": f"20{rnd.randint(18, 25)}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}",
        })
    return meters


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="config/meters.json")
    args = ap.parse_args()
    meters = make_meters(args.count, args.seed)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(meters, fh, ensure_ascii=False, indent=1)
    print(f"wrote {len(meters)} meters to {args.out}")


if __name__ == "__main__":
    main()
