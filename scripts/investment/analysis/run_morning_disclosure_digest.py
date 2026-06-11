#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect TDnet disclosures and generate the morning disclosure digest draft.")
    p.add_argument("--date", default=date.today().isoformat(), help="Target date (YYYY-MM-DD)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "topics/investment-research/inbox",
        help="Directory where markdown outputs will be written.",
    )
    p.add_argument("--skip-collect", action="store_true")
    p.add_argument("--lookback-days", type=int, default=1, help="TDnet collection lookback days")
    p.add_argument("--max-items", type=int, default=120)
    p.add_argument("--timeout", type=float, default=8.0)
    p.add_argument("--limit", type=int, default=20)
    return p.parse_args()


def run(cmd: list[str]) -> int:
    print("+ " + " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT)


def main() -> int:
    args = parse_args()
    py = sys.executable
    rc = 0
    if not args.skip_collect:
        rc |= run(
            [
                py,
                "scripts/investment/collect/collect_tdnet_disclosures.py",
                "--date",
                args.date,
                "--db",
                str(args.db),
                "--lookback-days",
                str(max(0, args.lookback_days)),
                "--max-items",
                str(max(1, args.max_items)),
                "--timeout",
                str(max(0.1, args.timeout)),
            ]
        )
    rc |= run(
        [
            py,
            "scripts/investment/analysis/generate_disclosure_digest.py",
            "--date",
            args.date,
                "--db",
                str(args.db),
                "--output-dir",
                str(args.output_dir),
                "--lookback-days",
                str(max(1, args.lookback_days)),
                "--limit",
                str(max(1, args.limit)),
            ]
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
