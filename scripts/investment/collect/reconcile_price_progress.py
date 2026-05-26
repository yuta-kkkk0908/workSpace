#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Reconcile price backfill progress with exception labels")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--target-bars", type=int, default=200, choices=[200, 500])
    p.add_argument("--new-listing-days", type=int, default=60)
    p.add_argument("--inactive-days", type=int, default=30)
    p.add_argument("--retry-fetch-errors", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    d = datetime.strptime(args.date, "%Y-%m-%d").date()
    new_cutoff = d - timedelta(days=args.new_listing_days)
    inactive_cutoff = d - timedelta(days=args.inactive_days)
    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    conn = sqlite3.connect(args.db)
    try:
        rows = conn.execute(
            """
            SELECT partition_key,bars_collected,status,error_message,last_date
            FROM collection_progress
            WHERE source='price_backfill_yahoo' AND bars_collected < ?
            """,
            (args.target_bars,),
        ).fetchall()
        relabeled = 0
        for ticker, bars, status, err, _ in rows:
            bars = int(bars or 0)
            first_date = conn.execute("SELECT MIN(date) FROM facts_price_daily WHERE ticker=?", (ticker,)).fetchone()[0]
            last_trade = conn.execute("SELECT MAX(date) FROM facts_price_daily WHERE ticker=?", (ticker,)).fetchone()[0]
            is_new = bool(first_date) and datetime.strptime(first_date, "%Y-%m-%d").date() >= new_cutoff
            is_inactive = bool(last_trade) and datetime.strptime(last_trade, "%Y-%m-%d").date() < inactive_cutoff
            is_fetch_error = (status or "").lower() == "error" or "fetch_failed" in (err or "")

            new_status = None
            note = ""
            if bars >= args.target_bars:
                continue
            if is_new:
                new_status = "exempt_new_listing"
                note = f"first_date={first_date}"
            elif is_inactive:
                new_status = "exempt_inactive"
                note = f"last_trade={last_trade}"
            elif is_fetch_error and not args.retry_fetch_errors:
                new_status = "retry_needed"
                note = (err or "fetch_failed")[:200]

            if new_status and new_status != (status or ""):
                conn.execute(
                    """
                    UPDATE collection_progress
                    SET status=?, error_message=?, updated_at=?
                    WHERE source='price_backfill_yahoo' AND partition_key=?
                    """,
                    (new_status, note, now_utc, ticker),
                )
                relabeled += 1
        conn.commit()
    finally:
        conn.close()
    print(f"reconcile_price_progress date={args.date} target={args.target_bars} relabeled={relabeled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

