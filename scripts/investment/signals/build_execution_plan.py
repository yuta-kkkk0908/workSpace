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
    direction = str(row.get("direction") or "").strip().lower()
    long_rank = str(row.get("long_rank") or "").strip()
    short_rank = str(row.get("short_rank") or "").strip()
    candidate_rank = str(row.get("candidate_rank") or "").strip()
    if candidate_rank:
        return candidate_rank
    if direction == "short":
        return short_rank
    if direction == "long":
        return long_rank
    return long_rank or short_rank


def parse_winrate_text(text: str) -> float | None:
    s = (text or "").strip()
    if not s:
        return None
    # examples: "T+1想定勝率=100.0%（50%超）"
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


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
        source_date = conn.execute(
            """
            SELECT max(scenario_date)
            FROM opening_scenarios
            WHERE scenario_date<=?
              AND scenario_date>=date(?, '-' || ? || ' days')
            """,
            (args.date, args.date, args.fallback_days),
        ).fetchone()[0]
        if not source_date:
            raise SystemExit(f"opening_scenarios not found in DB for {args.date} (fallback={args.fallback_days}d)")

        scenario_rows = conn.execute(
            """
            SELECT os.scenario_date, os.scenario_index, os.signal_id, os.ticker, os.company, os.direction, os.scenario_tier,
                   os.scenario_score, os.rule_hit_count, os.estimated_winrate_text, os.estimated_winrate_value,
                   os.entry_price, os.take_profit_price, os.stop_loss_price, os.source_url, os.source_path,
                   s.long_rank, s.short_rank,
                   (
                     SELECT ec.rank
                     FROM entry_candidates ec
                     WHERE ec.date=os.scenario_date
                       AND ec.ticker=os.ticker
                       AND lower(ec.side)=lower(os.direction)
                     ORDER BY CASE WHEN ec.candidate_type='primary' THEN 0 ELSE 1 END
                     LIMIT 1
                   ) AS candidate_rank,
                   (
                     SELECT fp.close
                     FROM facts_price_daily fp
                     WHERE fp.date=os.scenario_date
                       AND fp.ticker=os.ticker
                     LIMIT 1
                   ) AS close_price
            FROM opening_scenarios os
            LEFT JOIN signals s
              ON s.signal_id=os.signal_id
             AND s.date=os.scenario_date
            WHERE os.scenario_date=?
            ORDER BY os.scenario_index
            """,
            (source_date,),
        ).fetchall()
        if not scenario_rows:
            raise SystemExit(f"opening_scenarios not found in DB for {source_date}")

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
            if winrate_f is None:
                winrate_f = parse_winrate_text(str(r["estimated_winrate_text"] or ""))
            if entry_f is None and r["close_price"] is not None:
                try:
                    entry_f = float(r["close_price"])
                except Exception:
                    entry_f = None
            if entry_f is not None and (tp_f is None or sl_f is None):
                # Fallback bracket when scenario does not provide explicit prices.
                if direction == "long":
                    tp_f = tp_f if tp_f is not None else entry_f * 1.04
                    sl_f = sl_f if sl_f is not None else entry_f * 0.98
                else:
                    tp_f = tp_f if tp_f is not None else entry_f * 0.96
                    sl_f = sl_f if sl_f is not None else entry_f * 1.02
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
                    pick_rank(dict(r)),
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

    print(f"sourceDate={source_date}")
    print(f"wrote execution_plan rows={inserted} db={db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
