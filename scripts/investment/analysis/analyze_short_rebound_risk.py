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
OUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-rebound-risk-review.md"
OUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-rebound-risk-data.json"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        src = conn.execute(
            "SELECT ticker,signal_date,signal_type,short_readiness,short_use_case FROM short_readiness_rows WHERE date=?",
            (args.date,),
        ).fetchall()
        conn.execute("DELETE FROM short_rebound_reviews WHERE date=?", (args.date,))
        rows = []
        for r in src:
            action = "wait_for_failed_rebound" if (r["short_readiness"] or "").startswith("medium") else "buy_avoid_no_system_short"
            bucket = "rebound_risk_review"
            payload = {"ticker": r["ticker"], "signalDate": r["signal_date"], "signalType": r["signal_type"], "actionClass": action, "exclusionBucket": bucket}
            rows.append(payload)
            conn.execute(
                """
                INSERT INTO short_rebound_reviews(
                  date,ticker,signal_date,signal_type,exclusion_bucket,action_class,payload_json,updated_at
                ) VALUES(?,?,?,?,?,?,?,datetime('now'))
                """,
                (args.date, r["ticker"], r["signal_date"], r["signal_type"], bucket, action, json.dumps(payload, ensure_ascii=False)),
            )
        conn.commit()
    finally:
        conn.close()
    Path(str(OUT_JSON).format(date=args.date)).write_text(json.dumps({"date": args.date, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(str(OUT_MD).format(date=args.date)).write_text(f"# {args.date} Short Rebound Risk Review\n\n- rows: {len(rows)}\n", encoding="utf-8")
    print(f"rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
