#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def main() -> int:
    p = argparse.ArgumentParser(description="Check required signal fields in DB.")
    p.add_argument("--date", required=True)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    conn = sqlite3.connect(args.db)
    try:
        total = int(conn.execute("SELECT COUNT(*) FROM signals WHERE date=?", (args.date,)).fetchone()[0] or 0)
        missing = int(
            conn.execute(
                """
                SELECT COUNT(*) FROM signals
                WHERE date=?
                  AND (COALESCE(expected_direction,'')='' OR COALESCE(long_rank,'')='' OR COALESCE(short_rank,'')='')
                """,
                (args.date,),
            ).fetchone()[0]
            or 0
        )
    finally:
        conn.close()
    print(f"date={args.date} signals={total} missing_required={missing}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
