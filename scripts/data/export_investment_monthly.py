#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "investment.db"
DEFAULT_OUT = ROOT / "data" / "exports" / "investment"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export monthly investment data (Parquet preferred, CSV fallback)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--month", required=True, help="YYYY-MM")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    return p.parse_args()


def month_range(month: str) -> tuple[str, str]:
    dt = datetime.strptime(month, "%Y-%m")
    start = dt.strftime("%Y-%m-01")
    if dt.month == 12:
        nxt = datetime(dt.year + 1, 1, 1)
    else:
        nxt = datetime(dt.year, dt.month + 1, 1)
    return start, nxt.strftime("%Y-%m-%d")


def export_table(conn: sqlite3.Connection, table: str, date_col: str, start: str, end: str, out_dir: Path, month: str) -> str:
    query = f"SELECT * FROM {table} WHERE {date_col} >= ? AND {date_col} < ?"
    rows = conn.execute(query, (start, end)).fetchall()
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if not rows:
        return f"{table}:0"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"{table}-{month}"
    try:
        import pandas as pd  # type: ignore
        df = pd.DataFrame(rows, columns=cols)
        df.to_parquet(stem.with_suffix(".parquet"), index=False)
        return f"{table}:{len(rows)}:parquet"
    except Exception:
        import csv
        out_csv = stem.with_suffix(".csv")
        with out_csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            w.writerows(rows)
        return f"{table}:{len(rows)}:csv"


def main() -> int:
    args = parse_args()
    start, end = month_range(args.month)
    conn = sqlite3.connect(args.db)
    try:
        results = []
        results.append(export_table(conn, "facts_price_daily", "date", start, end, args.out_dir, args.month))
        results.append(export_table(conn, "raw_events", "ingest_date", start, end, args.out_dir, args.month))
        results.append(export_table(conn, "tdnet_disclosures", "date", start, end, args.out_dir, args.month))
    finally:
        conn.close()
    print("export_monthly", " ".join(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
