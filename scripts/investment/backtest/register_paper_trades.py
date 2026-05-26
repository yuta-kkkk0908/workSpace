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
    p = argparse.ArgumentParser(description="Register paper trades from opening scenarios")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--lots", type=int, default=1)
    p.add_argument("--entry-style", default="close_market", choices=["close_market"])
    p.add_argument("--max-trades", type=int, default=3)
    p.add_argument("--mode", default="backtest", choices=["backtest", "live", "watch"])
    p.add_argument("--tier", default="all", choices=["all", "trade", "watch"])
    p.add_argument("--fallback-days", type=int, default=0)
    return p.parse_args()


def side_to_sign(side: str) -> int:
    return 1 if side == "long" else -1


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"db not found: {db}")
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        where_tier = ""
        target_date = args.date
        params: list[object] = [target_date]
        if args.tier in {"trade", "watch"}:
            where_tier = " AND scenario_tier=?"
            params.append(args.tier)
        params.append(args.max_trades)
        rows = conn.execute(
            f"""
            SELECT scenario_date,ticker,company,direction,entry_price,signal_id,source_path,scenario_tier,source_kind
            FROM opening_scenarios
            WHERE scenario_date=? AND source_kind IN ('scenario','rejected'){where_tier}
            ORDER BY scenario_index
            LIMIT ?
            """,
            params,
        ).fetchall()
        if (not rows) and args.fallback_days > 0:
            params_fb: list[object] = [args.date, args.date, args.fallback_days]
            if args.tier in {"trade", "watch"}:
                params_fb.append(args.tier)
            params_fb.append(args.max_trades)
            rows = conn.execute(
                f"""
                SELECT scenario_date,ticker,company,direction,entry_price,signal_id,source_path,scenario_tier,source_kind
                FROM opening_scenarios
                WHERE scenario_date < ? AND scenario_date >= date(?, '-' || ? || ' day')
                  AND source_kind IN ('scenario','rejected'){where_tier}
                ORDER BY scenario_date DESC, scenario_index
                LIMIT ?
                """,
                params_fb,
            ).fetchall()
            if rows:
                target_date = str(rows[0]["scenario_date"] or args.date)
        inserted = 0
        for i, r in enumerate(rows, 1):
            ticker = str(r["ticker"] or "").strip()
            side = str(r["direction"] or "").strip()
            company = str(r["company"] or "").strip()
            if not ticker or side not in {"long", "short"}:
                continue
            tier = str(r["scenario_tier"] or "trade").strip().lower() or "trade"
            trade_id = f"paper_{args.mode}_{target_date.replace('-','')}_{ticker}_{side}_{tier}_{i:02d}"
            signal_id = str(r["signal_id"] or "")
            planned = r["entry_price"]
            if planned is None:
                # rejected/watch rows may not carry entry_price; use same-day close as neutral proxy.
                px = conn.execute(
                    "SELECT close FROM facts_price_daily WHERE date=? AND ticker=?",
                    (target_date, ticker),
                ).fetchone()
                if px:
                    planned = px[0]
            conn.execute(
                """
                INSERT INTO paper_trades(
                  trade_id, mode, entry_date, ticker, company, side, lots, entry_style,
                  planned_entry_price, status, signal_id, source_path, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(trade_id) DO UPDATE SET
                  mode=excluded.mode,company=excluded.company,lots=excluded.lots,entry_style=excluded.entry_style,
                  planned_entry_price=excluded.planned_entry_price,status=excluded.status,
                  signal_id=excluded.signal_id,source_path=excluded.source_path,updated_at=excluded.updated_at
                """,
                (
                    trade_id,
                    args.mode,
                    target_date,
                    ticker,
                    company,
                    side,
                    args.lots,
                    args.entry_style,
                    planned,
                    "open_pending_outcome",
                    signal_id,
                    str(r["source_path"] or "db:opening_scenarios"),
                    now(),
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    print(f"registered paper trades: {inserted} from db:opening_scenarios mode={args.mode} tier={args.tier} sourceDate={target_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
