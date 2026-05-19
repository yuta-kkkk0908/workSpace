#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pipeline launcher")
    p.add_argument("mode", choices=["daily", "deep"])
    p.add_argument("--date", required=True, help="Target date (YYYY-MM-DD)")
    p.add_argument("--seed-list")
    p.add_argument("--min-count", type=int, default=8)
    p.add_argument("--cache-only", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    module = f"scripts.pipelines.{args.mode}"
    cmd = [sys.executable, "-m", module, "--date", args.date, "--min-count", str(args.min_count)]
    if args.seed_list:
        cmd.extend(["--seed-list", args.seed_list])
    if args.cache_only:
        cmd.append("--cache-only")
    if args.dry_run:
        cmd.append("--dry-run")
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
