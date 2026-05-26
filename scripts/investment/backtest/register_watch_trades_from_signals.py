#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Register watch-mode shadow paper trades from signals")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--source", default="technical_daily")
    p.add_argument("--max-per-day", type=int, default=12)
    p.add_argument("--lots", type=int, default=1)
    return p.parse_args()


def side_from_expected(expected: str) -> str | None:
    e = (expected or "").lower()
    if e.startswith("up"):
        return "long"
    if e.startswith("down"):
        return "short"
    return None


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        days = [r[0] for r in conn.execute("SELECT DISTINCT date FROM signals WHERE date BETWEEN ? AND ? ORDER BY date", (args.start_date, args.end_date)).fetchall()]
        inserted = 0
        for d in days:
            rows = conn.execute(
                """
                SELECT signal_id,date,ticker,company,expected_direction,long_rank,short_rank
                FROM signals
                WHERE date=? AND source=?
                ORDER BY CASE WHEN long_rank LIKE 'A%%' OR short_rank LIKE 'A%%' THEN 0
                              WHEN long_rank LIKE 'B%%' OR short_rank LIKE 'B%%' THEN 1
                              ELSE 2 END,
                         signal_id
                LIMIT ?
                """,
                (d, args.source, args.max_per_day),
            ).fetchall()
            for i, r in enumerate(rows, start=1):
                ticker = str(r["ticker"] or "").strip()
                if not ticker:
                    continue
                side = side_from_expected(str(r["expected_direction"] or ""))
                if not side:
                    continue
                px = conn.execute(
                    "SELECT close FROM facts_price_daily WHERE date=? AND ticker=?",
                    (d, ticker),
                ).fetchone()
                planned = float(px[0]) if px and px[0] is not None else None
                trade_id = f"paper_watch_{d.replace('-', '')}_{ticker}_{side}_signal_{i:02d}"
                conn.execute(
                    """
                    INSERT INTO paper_trades(
                      trade_id,mode,entry_date,ticker,company,side,lots,entry_style,
                      planned_entry_price,status,signal_id,source_path,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(trade_id) DO UPDATE SET
                      company=excluded.company,planned_entry_price=excluded.planned_entry_price,
                      signal_id=excluded.signal_id,updated_at=excluded.updated_at
                    """,
                    (
                        trade_id,
                        "watch",
                        d,
                        ticker,
                        str(r["company"] or ""),
                        side,
                        args.lots,
                        "close_market",
                        planned,
                        "open_pending_outcome",
                        str(r["signal_id"] or ""),
                        f"db:signals:{args.source}",
                        now(),
                    ),
                )
                inserted += 1
        conn.commit()
    finally:
        conn.close()
    print(f"registered watch shadow trades: {inserted} source={args.source} range={args.start_date}..{args.end_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
