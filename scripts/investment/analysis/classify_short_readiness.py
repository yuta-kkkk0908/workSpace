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
OUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-readiness-data.json"
OUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-readiness-summary.md"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Classify short readiness (DB-first).")
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def classify(expected: str, short_rank: str) -> tuple[str, str]:
    e = (expected or "").lower()
    r = (short_rank or "").upper()
    if e.startswith("down") and r.startswith("A"):
        return "high", "short_entry_candidate"
    if e.startswith("down") and r.startswith("B"):
        return "medium", "short_entry_candidate"
    if e.startswith("down"):
        return "watch_needs_confirmation", "short_entry_candidate"
    return "not_entry", "buy_avoid_rebound_risk"


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT s.ticker,s.company,b.signal_date,s.signal_type,b.disclosure_category,s.expected_direction,s.short_rank,
                   b.t1_judge,b.t5_judge,b.t20_judge
            FROM backtest_outcomes b
            LEFT JOIN signals s ON s.signal_id=b.source_signal_id AND s.date=?
            WHERE b.date=? AND COALESCE(b.ticker,'')<>''
            ORDER BY b.signal_date,b.ticker
            """,
            (args.date, args.date),
        ).fetchall()
        out = []
        conn.execute("DELETE FROM short_readiness_rows WHERE date=?", (args.date,))
        seen: set[tuple[str, str, str]] = set()
        for r in rows:
            readiness, use_case = classify(r["expected_direction"] or "", r["short_rank"] or "")
            item = {
                "ticker": r["ticker"] or "",
                "company": r["company"] or "",
                "signalDate": r["signal_date"] or "",
                "category": r["disclosure_category"] or "",
                "signalType": r["signal_type"] or "",
                "shortRank": r["short_rank"] or "",
                "expected": r["expected_direction"] or "",
                "shortUseCase": use_case,
                "shortReadiness": readiness,
                "borrow_borrowStatus": "unknown",
                "liquidityBucket": "unknown",
                "avgTurnoverYen": None,
                "t1": r["t1_judge"] or "pending",
                "t5": r["t5_judge"] or "pending",
                "t20": r["t20_judge"] or "pending",
                "shortReadinessReasons": ["db_first_minimal"],
                "borrowCheck": "required",
            }
            key = (item["ticker"], item["signalDate"], item["signalType"])
            if not item["ticker"] or not item["signalDate"] or key in seen:
                continue
            seen.add(key)
            out.append(item)
            conn.execute(
                """
                INSERT OR REPLACE INTO short_readiness_rows(
                  date,ticker,signal_date,signal_type,company,category,short_rank,expected_direction,short_use_case,
                  short_readiness,borrow_status,liquidity_bucket,avg_turnover_yen,t1,t5,t20,reasons_json,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    args.date,
                    item["ticker"],
                    item["signalDate"],
                    item["signalType"],
                    item["company"],
                    item["category"],
                    item["shortRank"],
                    item["expected"],
                    item["shortUseCase"],
                    item["shortReadiness"],
                    item["borrow_borrowStatus"],
                    item["liquidityBucket"],
                    item["avgTurnoverYen"],
                    item["t1"],
                    item["t5"],
                    item["t20"],
                    json.dumps(item["shortReadinessReasons"], ensure_ascii=False),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    Path(str(OUT_JSON).format(date=args.date)).write_text(
        json.dumps({"date": args.date, "mode": "short-readiness-classification", "rows": out}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(str(OUT_MD).format(date=args.date)).write_text(f"# {args.date} Short Readiness Summary\n\n- rows: {len(out)}\n", encoding="utf-8")
    print(f"rows={len(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
