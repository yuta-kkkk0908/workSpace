#!/usr/bin/env python3
from __future__ import annotations

import argparse

from scripts.pipelines.common import run_cmd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run deep investment pipeline")
    p.add_argument("--date", required=True, help="Target date (YYYY-MM-DD)")
    p.add_argument("--seed-list", default="rough_backtest_full")
    p.add_argument("--min-count", type=int, default=8)
    p.add_argument("--cache-only", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cmd = [
        "make",
        "investment-backtest-expand",
        f"DATE={args.date}",
        f"SEED_LIST={args.seed_list}",
        f"MIN_COUNT={args.min_count}",
    ]
    if args.cache_only:
        cmd.append("CACHE_ONLY=1")
    run_cmd(cmd, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
