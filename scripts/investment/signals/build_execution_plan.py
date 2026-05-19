#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
JST = timezone(timedelta(hours=9))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build execution_plan rows from opening scenarios")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    p.add_argument("--db", default=str(DEFAULT_DB))
    return p.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def pick_rank(row: dict) -> str:
    txt = " ".join([str(x) for x in (row.get("rationale", []) or [])])
    m = re.search(r"rank=([A-Z][+-]?)", txt)
    return m.group(1) if m else ""


def compute_rr_ev(direction: str, entry: float | None, tp: float | None, sl: float | None, winrate_value: float | None) -> tuple[float | None, float | None]:
    if entry is None or tp is None or sl is None:
        return None, None
    if direction == "long":
        reward = tp - entry
        risk = entry - sl
    else:
        reward = entry - tp
        risk = sl - entry
    if risk <= 0:
        return None, None
    rr = reward / risk
    if winrate_value is None:
        return rr, None
    p = max(0.0, min(1.0, float(winrate_value) / 100.0))
    ev = p * reward - (1.0 - p) * risk
    return rr, ev


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        scenario_rows = conn.execute(
            """
            SELECT scenario_date, scenario_index, signal_id, ticker, company, direction, scenario_tier,
                   scenario_score, rule_hit_count, estimated_winrate_text, estimated_winrate_value,
                   entry_price, take_profit_price, stop_loss_price, source_url, source_path
            FROM opening_scenarios
            WHERE scenario_date=?
            ORDER BY scenario_index
            """,
            (args.date,),
        ).fetchall()
        if not scenario_rows:
            raise SystemExit(f"opening_scenarios not found in DB for {args.date}")

        inserted = 0
        for idx, r in enumerate(scenario_rows, 1):
            ticker = str(r["ticker"] or "").strip()
            if not ticker:
                continue
            direction = str(r["direction"] or "").strip().lower() or "short"
            tier = str(r["scenario_tier"] or "trade").strip() or "trade"
            signal_id = str(r["signal_id"] or "").strip()
            plan_id = f"{args.date.replace('-', '')}_{ticker}_{direction}_{tier}_{idx:02d}"
            entry = r["entry_price"]
            tp = r["take_profit_price"]
            sl = r["stop_loss_price"]
            try:
                entry_f = float(entry) if entry is not None else None
                tp_f = float(tp) if tp is not None else None
                sl_f = float(sl) if sl is not None else None
            except Exception:
                entry_f = tp_f = sl_f = None
            winrate_value = r["estimated_winrate_value"]
            try:
                winrate_f = float(winrate_value) if winrate_value is not None else None
            except Exception:
                winrate_f = None
            rr, ev = compute_rr_ev(direction, entry_f, tp_f, sl_f, winrate_f)
            reasons_obj = {
                "trigger": "",
                "ruleReproducibility": "",
                "estimatedWinRate": r["estimated_winrate_text"] or "",
                "scenarioScore": int(r["scenario_score"] or 0),
                "ruleHitCount": int(r["rule_hit_count"] or 0),
                "sourceUrl": r["source_url"] or "",
            }
            conn.execute(
                """
                INSERT INTO execution_plan(
                  plan_id, plan_date, ticker, company, direction, entry, tp, sl, rr, ev, rank, reasons, scenario_tier, status, signal_id, source_path, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(plan_id) DO UPDATE SET
                  ticker=excluded.ticker,
                  company=excluded.company,
                  direction=excluded.direction,
                  entry=excluded.entry,
                  tp=excluded.tp,
                  sl=excluded.sl,
                  rr=excluded.rr,
                  ev=excluded.ev,
                  rank=excluded.rank,
                  reasons=excluded.reasons,
                  scenario_tier=excluded.scenario_tier,
                  status=excluded.status,
                  signal_id=excluded.signal_id,
                  source_path=excluded.source_path,
                  updated_at=excluded.updated_at
                """,
                (
                    plan_id,
                    args.date,
                    ticker,
                    str(r["company"] or ""),
                    direction,
                    entry_f,
                    tp_f,
                    sl_f,
                    rr,
                    ev,
                    "",
                    json.dumps(reasons_obj, ensure_ascii=False),
                    tier,
                    "pending",
                    signal_id,
                    str(r["source_path"] or ""),
                    now_iso(),
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()

    print(f"sourceDate={args.date}")
    print(f"wrote execution_plan rows={inserted} db={db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
