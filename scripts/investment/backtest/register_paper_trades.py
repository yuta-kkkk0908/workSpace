#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
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
    p.add_argument("--mode", default="backtest", choices=["backtest", "live"])
    return p.parse_args()


def find_scenario(date_str: str) -> Path:
    p = INBOX / f"{date_str}-opening-scenarios.json"
    if not p.exists():
        raise SystemExit(f"scenario file not found: {p}")
    return p


def side_to_sign(side: str) -> int:
    return 1 if side == "long" else -1


def main() -> int:
    args = parse_args()
    src = find_scenario(args.date)
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = data.get("scenarios", [])[: args.max_trades]

    db = Path(args.db)
    conn = sqlite3.connect(db)
    try:
        inserted = 0
        for i, r in enumerate(rows, 1):
            ticker = str(r.get("ticker", "")).strip()
            side = str(r.get("direction", "")).strip()
            company = str(r.get("company", "")).strip()
            if not ticker or side not in {"long", "short"}:
                continue
            trade_id = f"paper_{args.mode}_{args.date.replace('-','')}_{ticker}_{side}_{i:02d}"
            signal_id = ""
            for part in r.get("rationale", []):
                if isinstance(part, str) and part.startswith("signalId="):
                    signal_id = part.split("=", 1)[1]
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
                    args.date,
                    ticker,
                    company,
                    side,
                    args.lots,
                    args.entry_style,
                    r.get("entryPrice"),
                    "open_pending_outcome",
                    signal_id,
                    str(src.relative_to(ROOT)),
                    now(),
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    print(f"registered paper trades: {inserted} from {src.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
