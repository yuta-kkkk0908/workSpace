#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()
JST = timezone(timedelta(hours=9))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Snapshot the latest available close for tickers surfaced in the current signal universe."
    )
    p.add_argument("--date", required=True, help="Signals date to read from (YYYY-MM-DD)")
    p.add_argument(
        "--snapshot-date",
        default=None,
        help="Date to write the snapshot under (YYYY-MM-DD). Defaults to --date.",
    )
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--slot", default="inv-evening-preclose")
    p.add_argument("--snapshot-time", default="06:00:00", help="Synthetic snapshot time used for the price snapshot")
    return p.parse_args()


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (name,)).fetchone()
    return bool(row)


def fetch_signal_tickers(conn: sqlite3.Connection, target_date: str) -> list[str]:
    if not table_exists(conn, "signals"):
        return []
    rows = conn.execute(
        "SELECT DISTINCT ticker FROM signals WHERE date=? AND COALESCE(ticker,'')<>'' ORDER BY ticker",
        (target_date,),
    ).fetchall()
    return [str(r[0]) for r in rows if str(r[0]).strip()]


def fetch_latest_close(conn: sqlite3.Connection, ticker: str, target_date: str) -> dict[str, Any] | None:
    if not table_exists(conn, "facts_price_daily"):
        return None
    row = conn.execute(
        """
        SELECT date, open, high, low, close, volume, source_kind, source_url
        FROM facts_price_daily
        WHERE ticker=? AND date<=?
        ORDER BY date DESC
        LIMIT 1
        """,
        (ticker, target_date),
    ).fetchone()
    if not row:
        return None
    latest = dict(row)
    prev = conn.execute(
        """
        SELECT date, close
        FROM facts_price_daily
        WHERE ticker=? AND date<?
        ORDER BY date DESC
        LIMIT 1
        """,
        (ticker, str(latest["date"] or "")),
    ).fetchone()
    prev_date = str(prev["date"]) if prev else ""
    prev_close = float(prev["close"]) if prev and prev["close"] not in (None, "") else None
    close = float(latest["close"]) if latest["close"] not in (None, "") else None
    ret_pct = ((close / prev_close - 1.0) * 100.0) if close and prev_close and prev_close > 0 else None
    latest["prev_close"] = prev_close
    latest["prev_close_date"] = prev_date
    latest["return_pct"] = ret_pct
    return latest


def upsert_snapshot(
    conn: sqlite3.Connection,
    target_date: str,
    slot: str,
    snapshot_time: str,
    ticker: str,
    latest: dict[str, Any],
) -> None:
    close = latest.get("close")
    volume = latest.get("volume")
    price = float(close) if close not in (None, "") else None
    source_date = str(latest.get("date") or "")
    conn.execute(
        """
        INSERT INTO market_signal_snapshots(
          date,ticker,slot,snapshot_time,price,vwap,vwap_gap_pct,return_pct,volume,volume_ratio,
          source_kind,source_ref,payload_json,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        ON CONFLICT(date,ticker,slot,snapshot_time) DO UPDATE SET
          price=excluded.price,
          vwap=excluded.vwap,
          vwap_gap_pct=excluded.vwap_gap_pct,
          return_pct=excluded.return_pct,
          volume=excluded.volume,
          volume_ratio=excluded.volume_ratio,
          source_kind=excluded.source_kind,
          source_ref=excluded.source_ref,
          payload_json=excluded.payload_json,
          updated_at=excluded.updated_at
        """,
        (
            target_date,
            ticker,
            slot,
            f"{target_date} {snapshot_time}",
            price,
            price,
            0.0 if price is not None else None,
            latest.get("return_pct"),
            int(volume) if volume not in (None, "") else None,
            None,
            "facts_price_daily_latest_close",
            f"facts_price_daily:{source_date}",
            json.dumps(
                {
                    "source_date": source_date,
                    "prev_close_date": str(latest.get("prev_close_date") or ""),
                    "source_kind": str(latest.get("source_kind") or ""),
                    "source_url": str(latest.get("source_url") or ""),
                    "snapshot_kind": "signal_close",
                },
                ensure_ascii=False,
            ),
        ),
    )


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    snapshot_date = args.snapshot_date or args.date
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        if not table_exists(conn, "market_signal_snapshots"):
            raise SystemExit("market_signal_snapshots table not found")
        tickers = fetch_signal_tickers(conn, args.date)
        if not tickers:
            print(f"signal_price_snapshot signals_date={args.date} snapshot_date={snapshot_date} tickers=0")
            return 0
        conn.execute("DELETE FROM market_signal_snapshots WHERE date=? AND slot=?", (snapshot_date, args.slot))
        inserted = 0
        for ticker in tickers:
            latest = fetch_latest_close(conn, ticker, args.date)
            if not latest:
                continue
            upsert_snapshot(conn, snapshot_date, args.slot, args.snapshot_time, ticker, latest)
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    print(
        f"signal_price_snapshot signals_date={args.date} snapshot_date={snapshot_date} slot={args.slot} inserted={inserted}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
