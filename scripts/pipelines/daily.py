#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.pipelines.common import run_cmd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run daily lightweight investment pipeline")
    p.add_argument("--date", required=True, help="Target date (YYYY-MM-DD)")
    p.add_argument("--seed-list", default="rough_backtest_light")
    p.add_argument("--min-count", type=int, default=8)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    run_cmd([
        "make",
        "investment-adaptive",
        f"DATE={args.date}",
        f"SEED_LIST={args.seed_list}",
        f"MIN_COUNT={args.min_count}",
    ], dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
