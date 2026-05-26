#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cleanup old raw_events rows by ingest_date")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--as-of-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--keep-days", type=int, default=14)
    p.add_argument("--source-kind", default="", help="optional source_kind filter")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    as_of = datetime.strptime(args.as_of_date, "%Y-%m-%d").date()
    cutoff = (as_of - timedelta(days=max(1, args.keep_days))).strftime("%Y-%m-%d")
    conn = sqlite3.connect(args.db)
    try:
        if args.source_kind.strip():
            cur = conn.execute(
                "DELETE FROM raw_events WHERE source_kind=? AND ingest_date < ?",
                (args.source_kind.strip(), cutoff),
            )
        else:
            cur = conn.execute("DELETE FROM raw_events WHERE ingest_date < ?", (cutoff,))
        conn.commit()
        print(f"cleanup_raw_events cutoff={cutoff} deleted={cur.rowcount}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
