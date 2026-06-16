#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db
from utils.pipeline_events import write_pipeline_event

DEFAULT_DB = resolve_investment_db()
OUT = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily KPI for paper_trade_only cohort")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def _max_drawdown(returns_pct: list[float]) -> float:
    if not returns_pct:
        return 0.0
    equity = 1.0
    peak = 1.0
    mdd = 0.0
    for r in returns_pct:
        equity *= 1.0 + (r / 100.0)
        if equity > peak:
            peak = equity
        dd = (equity / peak) - 1.0
        if dd < mdd:
            mdd = dd
    return mdd * 100.0


def _parse_price_path_summary(raw: str | None) -> dict[str, float | int | None]:
    if not raw:
        return {"available": 0, "t10_return_pct": None, "max_drawdown_pct": None, "path_days": None}
    try:
        payload = json.loads(raw)
    except Exception:
        return {"available": 0, "t10_return_pct": None, "max_drawdown_pct": None, "path_days": None}
    if not isinstance(payload, dict):
        return {"available": 0, "t10_return_pct": None, "max_drawdown_pct": None, "path_days": None}
    bars = payload.get("bars") or []
    if not isinstance(bars, list) or not bars:
        return {"available": 0, "t10_return_pct": None, "max_drawdown_pct": None, "path_days": None}
    base = None
    if payload.get("base_close") is not None:
        try:
            base = float(payload.get("base_close"))
        except Exception:
            base = None
    closes: list[float] = []
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        close = bar.get("close")
        try:
            if close is None:
                continue
            closes.append(float(close))
        except Exception:
            continue
    if not closes:
        return {"available": 0, "t10_return_pct": None, "max_drawdown_pct": None, "path_days": None}
    if base is None:
        try:
            base = float(closes[0])
        except Exception:
            base = None
    if base is None or base == 0:
        return {"available": 1, "t10_return_pct": None, "max_drawdown_pct": None, "path_days": len(closes)}
    t10 = ((closes[min(len(closes) - 1, 10)] / base) - 1.0) * 100.0
    path_rets = [((c / base) - 1.0) * 100.0 for c in closes]
    return {
        "available": 1,
        "t10_return_pct": t10,
        "max_drawdown_pct": _max_drawdown(path_rets),
        "path_days": len(closes),
    }


def main() -> int:
    args = parse_args()
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    start = (d0 - timedelta(days=max(1, int(args.window_days)) - 1)).isoformat()
    end = args.date

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT p.trade_id,p.entry_date,p.ticker,p.side,p.t1_return_pct,p.t5_return_pct,p.t20_return_pct,p.t5_judge,p.price_path_json
            FROM paper_trades p
            LEFT JOIN opening_scenarios os
              ON os.scenario_date=p.entry_date
             AND os.ticker=p.ticker
             AND lower(os.direction)=lower(p.side)
             AND COALESCE(os.signal_id,'')=COALESCE(p.signal_id,'')
            WHERE p.mode='watch'
              AND p.entry_date BETWEEN ? AND ?
              AND COALESCE(os.scenario_tier,'')='paper_trade_only'
            ORDER BY p.entry_date, p.trade_id
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()

    total = len(rows)
    judged_t5 = [float(r["t5_return_pct"]) for r in rows if r["t5_return_pct"] is not None]
    wins_t5 = sum(1 for r in judged_t5 if r > 0.0)
    winrate_t5 = (wins_t5 / len(judged_t5) * 100.0) if judged_t5 else 0.0
    ev_t5 = (sum(judged_t5) / len(judged_t5)) if judged_t5 else 0.0
    mdd_t5 = _max_drawdown(judged_t5)
    shortage_rate = ((total - len(judged_t5)) / total) if total > 0 else 0.0
    path_summaries = [_parse_price_path_summary(r["price_path_json"]) for r in rows]
    available_paths = [p for p in path_summaries if p.get("available")]
    t3_values = []
    for r in rows:
        raw = r["price_path_json"]
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        bars = payload.get("bars") or []
        if not isinstance(bars, list) or len(bars) <= 3:
            continue
        base = payload.get("base_close")
        try:
            base_f = float(base)
        except Exception:
            continue
        if base_f == 0:
            continue
        bar = bars[3]
        if not isinstance(bar, dict):
            continue
        try:
            close = float(bar.get("close"))
        except Exception:
            continue
        sign = -1.0 if str(r["side"] or "").strip().lower() == "short" else 1.0
        t3_values.append(((close / base_f) - 1.0) * 100.0 * sign)
    t10_values = [float(p["t10_return_pct"]) for p in available_paths if p.get("t10_return_pct") is not None]
    path_mdds = [float(p["max_drawdown_pct"]) for p in available_paths if p.get("max_drawdown_pct") is not None]
    path_days = [int(p["path_days"]) for p in available_paths if p.get("path_days") is not None]
    winrate_t3 = (sum(1 for x in t3_values if x > 0.0) / len(t3_values) * 100.0) if t3_values else 0.0
    ev_t3 = (sum(t3_values) / len(t3_values)) if t3_values else 0.0
    mdd_t3 = _max_drawdown(t3_values) if t3_values else 0.0
    winrate_t10 = (sum(1 for x in t10_values if x > 0.0) / len(t10_values) * 100.0) if t10_values else 0.0
    ev_t10 = (sum(t10_values) / len(t10_values)) if t10_values else 0.0
    mdd_t10 = _max_drawdown(t10_values) if t10_values else 0.0

    payload = {
        "date": args.date,
        "windowDays": int(args.window_days),
        "windowStart": start,
        "windowEnd": end,
        "kpi": {
            "sampleTrades": total,
            "judgedT5": len(judged_t5),
            "winRateT5Pct": round(winrate_t5, 3),
            "expectedValueT5Pct": round(ev_t5, 3),
            "maxDrawdownT5Pct": round(mdd_t5, 3),
            "sampleShortageRate": round(shortage_rate, 4),
            "pathsAvailable": len(available_paths),
            "judgedT3": len(t3_values),
            "winRateT3Pct": round(winrate_t3, 3),
            "expectedValueT3Pct": round(ev_t3, 3),
            "maxDrawdownT3Pct": round(mdd_t3, 3),
            "judgedT10": len(t10_values),
            "winRateT10Pct": round(winrate_t10, 3),
            "expectedValueT10Pct": round(ev_t10, 3),
            "maxDrawdownT10Pct": round(mdd_t10, 3),
            "averagePathDays": round((sum(path_days) / len(path_days)), 2) if path_days else 0.0,
        },
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-paper-trade-only-kpi.json"
        out_md = OUT / f"{args.date}-paper-trade-only-kpi.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {args.date} Paper Trade Only KPI",
            "",
            f"- window: {start} .. {end} ({int(args.window_days)}d)",
            f"- sampleTrades: {total}",
            f"- judgedT5: {len(judged_t5)}",
            f"- winRateT5Pct: {winrate_t5:.2f}",
            f"- expectedValueT5Pct: {ev_t5:.2f}",
            f"- maxDrawdownT5Pct: {mdd_t5:.2f}",
            f"- sampleShortageRate: {shortage_rate:.1%}",
            f"- pathsAvailable: {len(available_paths)}",
            f"- judgedT3: {len(t3_values)}",
            f"- winRateT3Pct: {winrate_t3:.2f}",
            f"- expectedValueT3Pct: {ev_t3:.2f}",
            f"- maxDrawdownT3Pct: {mdd_t3:.2f}",
            f"- judgedT10: {len(t10_values)}",
            f"- winRateT10Pct: {winrate_t10:.2f}",
            f"- expectedValueT10Pct: {ev_t10:.2f}",
            f"- maxDrawdownT10Pct: {mdd_t10:.2f}",
            f"- averagePathDays: {(sum(path_days) / len(path_days)):.2f}" if path_days else "- averagePathDays: 0.00",
        ]
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    write_pipeline_event(
        pipeline="investment_analysis",
        slot="inv-evening",
        stage="report_paper_trade_only_kpi",
        status="ok",
        event_date=args.date,
        return_code=0,
        payload=payload,
        source_path="scripts/investment/analysis/report_paper_trade_only_kpi.py",
    )
    print(
        "paper_trade_only_kpi date={0} sample={1} judged_t5={2} win={3:.3f} ev={4:.3f} mdd={5:.3f} shortage={6:.3f} t3={7} t10={8} path_avail={9}".format(
            args.date, total, len(judged_t5), winrate_t5, ev_t5, mdd_t5, shortage_rate, len(t3_values), len(t10_values), len(available_paths)
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
