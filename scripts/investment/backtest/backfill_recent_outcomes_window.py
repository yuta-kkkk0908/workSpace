#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill rough market outcomes for recent date window")
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--db-lookback-days", type=int, default=30)
    p.add_argument("--seed-list", default="rough_backtest_light")
    p.add_argument("--cache-only", action="store_true")
    p.add_argument("--max-failures", type=int, default=5)
    p.add_argument("--python", default=sys.executable)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    d0 = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    failures = 0
    ok = 0
    skip_weekend = 0
    for i in range(max(1, int(args.window_days))):
        d = (d0 - timedelta(days=i))
        # JP market holiday calendar is not available here; skip weekends.
        if d.weekday() >= 5:
            skip_weekend += 1
            continue
        ds = d.isoformat()
        cmd = [
            args.python,
            "scripts/investment/backtest/fill_market_outcomes.py",
            "--date",
            ds,
            "--seed-list",
            str(args.seed_list),
            "--include-db-signals",
            "--db-lookback-days",
            str(args.db_lookback_days),
        ]
        if args.cache_only:
            cmd.append("--cache-only")
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        if rc == 0:
            ok += 1
            continue
        failures += 1
        print(f"[warn] fill_market_outcomes failed date={ds} rc={rc}")
        if failures >= max(1, int(args.max_failures)):
            print(f"[stop] reached max_failures={args.max_failures}")
            break

    print(
        "backfill_recent_outcomes_window as_of={0} window_days={1} ok={2} failures={3} skipped_weekend={4}".format(
            args.as_of, int(args.window_days), ok, failures, skip_weekend
        )
    )
    return 0 if failures < max(1, int(args.max_failures)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
