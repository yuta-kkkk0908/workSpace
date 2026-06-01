#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill opening_scenarios/execution_plan for recent business days")
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    p.add_argument("--window-days", type=int, default=90, help="lookback window in calendar days")
    p.add_argument("--max-days-per-run", type=int, default=10, help="cap number of business days processed per run")
    p.add_argument("--python", default=sys.executable)
    return p.parse_args()


def run(cmd: list[str]) -> int:
    print("[run]", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


def main() -> int:
    args = parse_args()
    as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date()
    start = as_of - timedelta(days=max(0, args.window_days))

    # Process newer dates first so nightly runs quickly improve recent usability.
    targets: list[str] = []
    d = as_of
    while d >= start:
        if d.weekday() < 5:  # Mon-Fri
            targets.append(d.isoformat())
        d -= timedelta(days=1)
        if len(targets) >= max(1, args.max_days_per_run):
            break

    rc = 0
    for ds in targets:
        rc |= run(
            [
                args.python,
                "scripts/investment/signals/build_opening_scenarios.py",
                "--date",
                ds,
                "--fallback-days",
                "30",
                "--auto-relax-gate",
                "--allow-unknown-winrate",
                "--soft-gate",
                "--adaptive-side-minimum",
            ]
        )
        rc |= run([args.python, "scripts/investment/signals/build_execution_plan.py", "--date", ds, "--fallback-days", "30"])
        rc |= run([args.python, "scripts/investment/signals/fill_execution_plan_metrics.py", "--start-date", ds, "--end-date", ds])
        rc |= run(
            [
                args.python,
                "scripts/investment/backtest/register_paper_trades.py",
                "--date",
                ds,
                "--mode",
                "watch",
                "--tier",
                "all",
                "--max-trades",
                "12",
                "--fallback-days",
                "30",
            ]
        )

    print(f"backfilled_dates={len(targets)} as_of={args.as_of}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())

