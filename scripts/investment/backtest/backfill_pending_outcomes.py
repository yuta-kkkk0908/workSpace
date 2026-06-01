#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prioritize filling pending backtest outcomes for mature signal dates")
    p.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=90)
    p.add_argument("--max-dates", type=int, default=8)
    p.add_argument("--python", default=sys.executable)
    return p.parse_args()


def target_dates(db: Path, as_of: str, window_days: int, max_dates: int) -> list[str]:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT signal_date, COUNT(*) AS n
            FROM backtest_outcomes
            WHERE signal_date BETWEEN date(?, '-' || ? || ' day') AND date(?, '-5 day')
              AND (
                COALESCE(t1_judge,'')='pending' OR
                COALESCE(t5_judge,'')='pending' OR
                COALESCE(t20_judge,'')='pending'
              )
            GROUP BY signal_date
            ORDER BY n DESC, signal_date DESC
            LIMIT ?
            """,
            (as_of, window_days, as_of, max(1, max_dates)),
        ).fetchall()
        return [str(r[0]) for r in rows if r and r[0]]
    finally:
        conn.close()


def run(cmd: list[str]) -> int:
    print("[run]", " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT).returncode


def main() -> int:
    args = parse_args()
    datetime.strptime(args.as_of, "%Y-%m-%d")
    dates = target_dates(args.db, args.as_of, args.window_days, args.max_dates)
    rc = 0
    for ds in dates:
        rc |= run(
            [
                args.python,
                "scripts/investment/backtest/fill_market_outcomes.py",
                "--date",
                ds,
                "--seed-list",
                "rough_backtest_full",
                "--include-db-signals",
            ]
        )
    print(f"pending_target_dates={len(dates)} as_of={args.as_of}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
