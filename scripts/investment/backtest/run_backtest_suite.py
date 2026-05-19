#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def run(cmd: list[str], allow_fail: bool = False) -> int:
    print("[run]", " ".join(cmd))
    rc = subprocess.run(cmd, cwd=ROOT).returncode
    if rc != 0 and allow_fail:
        return 0
    return rc


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run investment backtest suite")
    p.add_argument("--date", default=date.today().isoformat(), help="YYYY-MM-DD")
    p.add_argument("--python", default=sys.executable)
    p.add_argument("--mode", choices=["quick", "deep", "deep-cache"], default="quick")
    p.add_argument("--seed-list")
    p.add_argument("--min-count", type=int, default=8)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    py = args.python
    d = args.date
    rc = 0

    if args.mode == "quick":
        seed = args.seed_list or "rough_backtest_light"
        rc |= run([py, "scripts/run_pipeline.py", "daily", "--date", d, "--seed-list", seed, "--min-count", str(args.min_count)])
        return rc

    if args.mode == "deep":
        seed = args.seed_list or "rough_backtest_full"
        rc |= run([py, "scripts/run_pipeline.py", "deep", "--date", d, "--seed-list", seed, "--min-count", str(args.min_count)])
        return rc

    if args.mode == "deep-cache":
        seed = args.seed_list or "rough_backtest_full"
        rc |= run(
            [
                py,
                "scripts/run_pipeline.py",
                "deep",
                "--date",
                d,
                "--seed-list",
                seed,
                "--min-count",
                str(args.min_count),
                "--cache-only",
            ]
        )
        return rc

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
