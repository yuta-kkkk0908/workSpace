#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_DB = ROOT / "data" / "investment.db"
OUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-high-readiness-review.md"
OUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-high-readiness-review-data.json"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM short_readiness_rows WHERE date=? AND short_readiness='high' ORDER BY ticker", (args.date,)).fetchall()
    finally:
        conn.close()
    payload = {"date": args.date, "rows": [dict(r) for r in rows]}
    Path(str(OUT_JSON).format(date=args.date)).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(str(OUT_MD).format(date=args.date)).write_text(f"# {args.date} Short High Readiness Review\n\n- rows: {len(rows)}\n", encoding="utf-8")
    print(f"rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
