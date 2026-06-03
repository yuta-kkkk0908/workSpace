#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Report placeholder company-name counts")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--date", help="YYYY-MM-DD (optional)")
    p.add_argument("--days", type=int, default=14, help="lookback days when --date is provided")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        def q(table: str, date_col: str = "date") -> list[tuple]:
            where = ""
            params: tuple = tuple()
            if args.date:
                where = f"WHERE {date_col} BETWEEN date(?, ?) AND ?"
                params = (args.date, f"-{max(0, int(args.days) - 1)} day", args.date)
            return conn.execute(
                f"""
                SELECT {date_col} AS d,
                       COUNT(*) AS total,
                       SUM(CASE WHEN UPPER(TRIM(COALESCE(company,''))) IN ('', '不明', '-', 'N/A', 'NA', 'UNKNOWN') THEN 1 ELSE 0 END) AS placeholders
                FROM {table}
                {where}
                GROUP BY {date_col}
                ORDER BY {date_col} DESC
                """,
                params,
            ).fetchall()

        sig = q("signals", "date")
        ec = q("entry_candidates", "date")
        osr = q("opening_scenarios", "scenario_date")

        print("== Placeholder Company Report ==")
        for name, rows in [("signals", sig), ("entry_candidates", ec), ("opening_scenarios", osr)]:
            print(f"[{name}]")
            if not rows:
                print("  (no rows)")
                continue
            for d, total, ph in rows[:20]:
                ratio = (ph / total * 100.0) if total else 0.0
                print(f"  {d}: placeholders={int(ph or 0)}/{int(total or 0)} ({ratio:.1f}%)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
