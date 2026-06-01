#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "investment.db"
DEFAULT_OUT = ROOT / "prompts" / "ai-investment-digest.txt"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render AI investment digest message from DB.")
    p.add_argument("--date", default=date.today().isoformat())
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--fallback-days", type=int, default=2)
    return p.parse_args()


def fetch_summary(conn: sqlite3.Connection, target_date: str, fallback_days: int) -> str | None:
    row = conn.execute(
        "SELECT summary FROM daily_digest WHERE topic='ai-investment-digest' AND date=?",
        (target_date,),
    ).fetchone()
    if row and row[0]:
        return str(row[0])
    d0 = date.fromisoformat(target_date)
    for i in range(1, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        r = conn.execute(
            "SELECT summary FROM daily_digest WHERE topic='ai-investment-digest' AND date=?",
            (d,),
        ).fetchone()
        if r and r[0]:
            return str(r[0])
    return None


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    try:
        summary = fetch_summary(conn, args.date, args.fallback_days)
    finally:
        conn.close()
    if not summary:
        raise SystemExit(f"ai-investment-digest not found in DB for {args.date}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(summary.rstrip() + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
