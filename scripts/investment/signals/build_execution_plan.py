#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
INBOX = ROOT / "topics" / "investment-research" / "inbox"
DEFAULT_DB = ROOT / "data" / "investment.db"
JST = timezone(timedelta(hours=9))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build execution_plan rows from opening scenarios")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    p.add_argument("--db", default=str(DEFAULT_DB))
    return p.parse_args()


def find_scenarios_json(date_str: str, fallback_days: int) -> tuple[Path, str]:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        p = INBOX / f"{d}-opening-scenarios.json"
        if p.exists():
            return p, d
    raise SystemExit(f"opening-scenarios not found for {date_str} (fallback_days={fallback_days})")


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
    src, src_date = find_scenarios_json(args.date, args.fallback_days)
    payload = json.loads(src.read_text(encoding="utf-8"))
    rows = payload.get("scenarios", []) or []
    rejected = payload.get("rejectedScenarios", []) or []
    merged = []
    for r in rows:
        x = dict(r)
        x["scenarioTier"] = str(r.get("scenarioTier") or "trade")
        merged.append(x)
    for r in rejected:
        x = dict(r)
        x["scenarioTier"] = "watch"
        merged.append(x)

    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        inserted = 0
        for idx, r in enumerate(merged, 1):
            ticker = str(r.get("ticker", "")).strip()
            if not ticker:
                continue
            direction = str(r.get("direction", "")).strip().lower() or ("long" if str(r.get("expectedDirection", "")).startswith("up") else "short")
            tier = str(r.get("scenarioTier", "trade")).strip() or "trade"
            signal_id = str(r.get("signalId", "")).strip()
            plan_id = f"{args.date.replace('-', '')}_{ticker}_{direction}_{tier}_{idx:02d}"
            entry = r.get("entryPrice")
            tp = r.get("takeProfitPrice")
            sl = r.get("stopLossPrice")
            try:
                entry_f = float(entry) if entry is not None else None
                tp_f = float(tp) if tp is not None else None
                sl_f = float(sl) if sl is not None else None
            except Exception:
                entry_f = tp_f = sl_f = None
            winrate_value = r.get("estimatedWinRateValue")
            try:
                winrate_f = float(winrate_value) if winrate_value is not None else None
            except Exception:
                winrate_f = None
            rr, ev = compute_rr_ev(direction, entry_f, tp_f, sl_f, winrate_f)
            reasons_obj = {
                "trigger": r.get("trigger", ""),
                "ruleReproducibility": r.get("ruleReproducibility", ""),
                "estimatedWinRate": r.get("estimatedWinRate", ""),
                "scenarioScore": r.get("scenarioScore", 0),
                "ruleHitCount": r.get("ruleHitCount", 0),
                "sourceUrl": r.get("sourceUrl", ""),
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
                    str(r.get("company", "")),
                    direction,
                    entry_f,
                    tp_f,
                    sl_f,
                    rr,
                    ev,
                    pick_rank(r),
                    json.dumps(reasons_obj, ensure_ascii=False),
                    tier,
                    "pending",
                    signal_id,
                    str(src.relative_to(ROOT)),
                    now_iso(),
                ),
            )
            inserted += 1
        conn.commit()
    finally:
        conn.close()

    print(f"sourceDate={src_date}")
    print(f"wrote execution_plan rows={inserted} db={db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

