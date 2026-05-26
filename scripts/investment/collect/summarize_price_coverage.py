#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize price coverage with exception buckets")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--target-bars", type=int, default=200, choices=[200, 500])
    p.add_argument("--new-listing-days", type=int, default=60)
    p.add_argument("--inactive-days", type=int, default=30)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    d = datetime.strptime(args.date, "%Y-%m-%d").date()
    new_cutoff = d - timedelta(days=args.new_listing_days)
    inactive_cutoff = d - timedelta(days=args.inactive_days)
    conn = sqlite3.connect(args.db)
    try:
        rows = conn.execute(
            """
            SELECT partition_key,bars_collected,status,error_message,last_date
            FROM collection_progress
            WHERE source='price_backfill_yahoo'
            """
        ).fetchall()
        eligible = 0
        ready = 0
        exceptions = {"new_listing": 0, "inactive_symbol": 0, "fetch_error": 0, "other": 0}
        detail = []
        for ticker, bars, status, err, last_date in rows:
            bars = int(bars or 0)
            first_date = conn.execute(
                "SELECT MIN(date) FROM facts_price_daily WHERE ticker=?",
                (ticker,),
            ).fetchone()[0]
            last_trade = conn.execute(
                "SELECT MAX(date) FROM facts_price_daily WHERE ticker=?",
                (ticker,),
            ).fetchone()[0]
            is_new = bool(first_date) and datetime.strptime(first_date, "%Y-%m-%d").date() >= new_cutoff
            is_inactive = bool(last_trade) and datetime.strptime(last_trade, "%Y-%m-%d").date() < inactive_cutoff
            is_fetch_error = (status or "").lower() == "error" or "fetch_failed" in (err or "")
            if bars >= args.target_bars:
                ready += 1
                eligible += 1
                continue
            if is_new:
                exceptions["new_listing"] += 1
                detail.append({"ticker": ticker, "kind": "new_listing", "bars": bars, "first_date": first_date, "last_date": last_trade})
                continue
            if is_inactive:
                exceptions["inactive_symbol"] += 1
                detail.append({"ticker": ticker, "kind": "inactive_symbol", "bars": bars, "first_date": first_date, "last_date": last_trade})
                continue
            if is_fetch_error:
                exceptions["fetch_error"] += 1
                eligible += 1
                detail.append({"ticker": ticker, "kind": "fetch_error", "bars": bars, "first_date": first_date, "last_date": last_trade})
                continue
            exceptions["other"] += 1
            eligible += 1
            detail.append({"ticker": ticker, "kind": "other", "bars": bars, "first_date": first_date, "last_date": last_trade})

        coverage_pct = (ready / eligible * 100.0) if eligible > 0 else 0.0
        payload = {
            "date": args.date,
            "target_bars": args.target_bars,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "ready": ready,
            "eligible": eligible,
            "coverage_pct": coverage_pct,
            "exceptions": exceptions,
            "details": detail,
        }
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collection_artifacts (
              artifact_key TEXT NOT NULL,
              artifact_date TEXT NOT NULL,
              artifact_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(artifact_key, artifact_date)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(artifact_key,artifact_date) DO UPDATE SET
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (
                f"price_coverage_summary_{args.target_bars}",
                args.date,
                "coverage_summary",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                payload["generated_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    print(
        f"price_coverage_summary date={args.date} target={args.target_bars} "
        f"ready={ready} eligible={eligible} coverage_pct={coverage_pct:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

