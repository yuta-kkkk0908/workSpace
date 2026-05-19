#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PROMPTS_DIR = ROOT / "prompts"
DEFAULT_NEEDS_DB = DATA_DIR / "needs.db"
JST = timezone(timedelta(hours=9))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build weekly needs freshness status from needs.db")
    p.add_argument("--needs-db", default=str(DEFAULT_NEEDS_DB.relative_to(ROOT)))
    p.add_argument("--out-status", default=str((PROMPTS_DIR / "needs-freshness.status.txt").relative_to(ROOT)))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    db_path = ROOT / args.needs_db
    out_status = ROOT / args.out_status
    out_status.parent.mkdir(parents=True, exist_ok=True)
    today = datetime.now(JST).date().isoformat()

    if not db_path.exists():
        out_status.write_text(
            f"Needs Freshness {today}\n- status: WARN\n- needs.db not found: {db_path.relative_to(ROOT)}\n",
            encoding="utf-8",
        )
        print("WARN: needs.db not found")
        return 1

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT MAX(date), MAX(updated_at), COUNT(1)
            FROM need_items
            """
        ).fetchone()
    finally:
        conn.close()

    last_date = row[0] if row and row[0] else ""
    last_updated_at = row[1] if row and row[1] else ""
    total_rows = int(row[2]) if row and row[2] is not None else 0
    status = "OK" if last_date else "WARN"

    lines = [
        f"Needs Freshness {today}",
        f"- status: {status}",
        f"- last_need_date: {last_date or '(none)'}",
        f"- last_updated_at: {last_updated_at or '(none)'}",
        f"- total_need_items: {total_rows}",
    ]
    out_status.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{status}: {out_status.relative_to(ROOT)}")
    return 0 if status == "OK" else 1


if __name__ == "__main__":
    raise SystemExit(main())
