#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Register paper trades from opening scenarios")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--lots", type=int, default=1)
    p.add_argument("--entry-style", default="close_market", choices=["close_market"])
    p.add_argument("--max-trades", type=int, default=3)
    p.add_argument("--mode", default="paper_history", choices=["paper_history", "live", "watch"])
    p.add_argument("--tier", default="all", choices=["all", "trade", "watch", "paper_trade_only"])
    p.add_argument("--rejected-policy", default="all", choices=["all", "weak_only", "data_quality_only", "other_only"])
    p.add_argument("--fallback-days", type=int, default=0)
    return p.parse_args()


def side_to_sign(side: str) -> int:
    return 1 if side == "long" else -1


def parse_reject_reasons(raw: str) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    try:
        data = json.loads(s)
    except Exception:
        return [s]
    if isinstance(data, list):
        return [str(x) for x in data if str(x or "").strip()]
    return [str(data)]


def is_weak_reject(reasons: list[str]) -> bool:
    for r in reasons:
        x = str(r or "")
        if x.startswith("ruleHits<") or x.startswith("score<") or x.startswith("winRate<"):
            return True
        if x in {"RULE_THIN_GATE", "RULE_THIN_RANK", "RULE_THIN_QUALITY"}:
            return True
    return False


def is_data_quality_reject(reasons: list[str]) -> bool:
    for r in reasons:
        x = str(r or "")
        if x in {"MATERIAL_NONE_TODAY", "NOON_DATA_GAP", "CREDIT_THIN"}:
            return True
        if x.startswith("sampleCount<"):
            return True
        if x.startswith("winRate_unknown"):
            return True
    return False


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"db not found: {db}")
    mode = "paper_history" if args.mode == "paper_history" else args.mode
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
            SELECT os.scenario_date,os.ticker,os.company,os.direction,os.entry_price,os.signal_id,os.source_path,os.scenario_tier,os.source_kind,
                   sg.reject_reasons_json
            FROM opening_scenarios os
            LEFT JOIN scenario_gate_diagnostics sg
              ON sg.scenario_date=os.scenario_date
             AND COALESCE(sg.signal_id,'')=COALESCE(os.signal_id,'')
             AND sg.ticker=os.ticker
             AND sg.direction=os.direction
             AND sg.gate_result='rejected'
            WHERE os.scenario_date=? AND os.source_kind IN ('scenario','rejected'){where_tier}
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
                SELECT os.scenario_date,os.ticker,os.company,os.direction,os.entry_price,os.signal_id,os.source_path,os.scenario_tier,os.source_kind,
                       sg.reject_reasons_json
                FROM opening_scenarios os
                LEFT JOIN scenario_gate_diagnostics sg
                  ON sg.scenario_date=os.scenario_date
                 AND COALESCE(sg.signal_id,'')=COALESCE(os.signal_id,'')
                 AND sg.ticker=os.ticker
                 AND sg.direction=os.direction
                 AND sg.gate_result='rejected'
                WHERE os.scenario_date < ? AND os.scenario_date >= date(?, '-' || ? || ' day')
                  AND os.source_kind IN ('scenario','rejected'){where_tier}
                ORDER BY os.scenario_date DESC, os.scenario_index
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
            source_kind = str(r["source_kind"] or "scenario").strip().lower() or "scenario"
            reject_reasons = parse_reject_reasons(str(r["reject_reasons_json"] or ""))
            weak_reject = is_weak_reject(reject_reasons)
            data_quality_reject = is_data_quality_reject(reject_reasons)
            if source_kind == "rejected":
                if args.rejected_policy == "weak_only" and not weak_reject:
                    continue
                if args.rejected_policy == "data_quality_only" and not data_quality_reject:
                    continue
                if args.rejected_policy == "other_only" and weak_reject:
                    continue
            trade_prefix = "paper_history" if mode == "paper_history" else f"paper_{mode}"
            trade_id = f"{trade_prefix}_{target_date.replace('-','')}_{ticker}_{side}_{tier}_{i:02d}"
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
            cohort = "promoted"
            if source_kind == "rejected":
                if weak_reject:
                    cohort = "rejected_weak"
                elif data_quality_reject:
                    cohort = "rejected_data_quality"
                else:
                    cohort = "rejected_other"
            source_path = str(r["source_path"] or "db:opening_scenarios")
            source_path = f"{source_path}#cohort={cohort}"
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
                        mode,
                        target_date,
                        ticker,
                    company,
                    side,
                    args.lots,
                    args.entry_style,
                    planned,
                    "open_pending_outcome",
                    signal_id,
                    source_path,
                    now(),
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()
    print(f"registered paper trades: {inserted} from db:opening_scenarios mode={mode} tier={args.tier} sourceDate={target_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
