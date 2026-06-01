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
from utils.pipeline_events import write_pipeline_event

DEFAULT_DB = ROOT / "data" / "investment.db"
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
            SELECT p.trade_id,p.entry_date,p.ticker,p.side,p.t1_return_pct,p.t5_return_pct,p.t20_return_pct,p.t5_judge
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
        "paper_trade_only_kpi date={0} sample={1} judged_t5={2} win={3:.3f} ev={4:.3f} mdd={5:.3f} shortage={6:.3f}".format(
            args.date, total, len(judged_t5), winrate_t5, ev_t5, mdd_t5, shortage_rate
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

