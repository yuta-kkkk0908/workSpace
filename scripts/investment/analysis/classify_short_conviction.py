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
OUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-conviction-report.md"
OUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-conviction-data.json"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        src = conn.execute("SELECT * FROM short_readiness_rows WHERE date=? ORDER BY ticker", (args.date,)).fetchall()
        conn.execute("DELETE FROM short_conviction_rows WHERE date=?", (args.date,))
        rows = []
        for r in src:
            sr = (r["short_readiness"] or "")
            if sr == "high":
                bucket = "strict_short_signal"
            elif sr.startswith("medium"):
                bucket = "return_short_wait"
            else:
                bucket = "buy_avoid_no_system_short"
            payload = {
                "ticker": r["ticker"],
                "signalDate": r["signal_date"],
                "signalType": r["signal_type"],
                "convictionBucket": bucket,
                "t1": r["t1"],
                "t5": r["t5"],
                "t20": r["t20"],
            }
            rows.append(payload)
            conn.execute(
                """
                INSERT INTO short_conviction_rows(
                  date,ticker,signal_date,signal_type,conviction_bucket,reasons_json,payload_json,updated_at
                ) VALUES(?,?,?,?,?,?,?,datetime('now'))
                """,
                (args.date, r["ticker"], r["signal_date"], r["signal_type"], bucket, json.dumps(["db_first_minimal"], ensure_ascii=False), json.dumps(payload, ensure_ascii=False)),
            )
        conn.commit()
    finally:
        conn.close()
    Path(str(OUT_JSON).format(date=args.date)).write_text(json.dumps({"date": args.date, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(str(OUT_MD).format(date=args.date)).write_text(f"# {args.date} Short Conviction Report\n\n- rows: {len(rows)}\n", encoding="utf-8")
    print(f"rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
