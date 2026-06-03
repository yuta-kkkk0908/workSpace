#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
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
    p = argparse.ArgumentParser(description="Daily failure-factor report for paper_trade_only cohort")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--loss-threshold-pct", type=float, default=-0.5)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def _session_bucket(d: str) -> str:
    if not d:
        return "unknown"
    try:
        wd = datetime.strptime(d, "%Y-%m-%d").weekday()
    except Exception:
        return "unknown"
    if wd == 0:
        return "mon"
    if wd == 4:
        return "fri"
    return "midweek"


def main() -> int:
    args = parse_args()
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    start = (d0 - timedelta(days=max(1, int(args.window_days)) - 1)).isoformat()
    end = args.date
    loss_th = float(args.loss_threshold_pct)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT p.trade_id,p.entry_date,p.ticker,p.side,p.t5_return_pct,
                   s.signal_type,s.credit_status,
                   m.margin_bucket,
                   sr.liquidity_bucket
            FROM paper_trades p
            LEFT JOIN opening_scenarios os
              ON os.scenario_date=p.entry_date
             AND os.ticker=p.ticker
             AND lower(os.direction)=lower(p.side)
             AND COALESCE(os.signal_id,'')=COALESCE(p.signal_id,'')
            LEFT JOIN signals s
              ON s.date=p.entry_date
             AND s.ticker=p.ticker
            LEFT JOIN margin_context_rows m
              ON m.date=p.entry_date
             AND m.ticker=p.ticker
            LEFT JOIN short_readiness_rows sr
              ON sr.date=p.entry_date
             AND sr.ticker=p.ticker
            WHERE p.mode='watch'
              AND p.entry_date BETWEEN ? AND ?
              AND os.scenario_tier='paper_trade_only'
              AND p.t5_return_pct IS NOT NULL
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()

    total = len(rows)
    losses = [r for r in rows if float(r["t5_return_pct"]) <= loss_th]
    loss_count = len(losses)

    by_credit = Counter(str(r["credit_status"] or "unknown") for r in losses)
    by_liq = Counter(str(r["liquidity_bucket"] or "unknown") for r in losses)
    by_margin = Counter(str(r["margin_bucket"] or "unknown") for r in losses)
    by_session = Counter(_session_bucket(str(r["entry_date"] or "")) for r in losses)
    by_signal_type = Counter(str(r["signal_type"] or "unknown") for r in losses)

    payload = {
        "date": args.date,
        "windowDays": int(args.window_days),
        "windowStart": start,
        "windowEnd": end,
        "lossThresholdPct": loss_th,
        "summary": {
            "sampleTrades": total,
            "lossCount": loss_count,
            "lossRate": round((loss_count / total), 4) if total > 0 else 0.0,
        },
        "lossFactors": {
            "creditStatus": dict(by_credit.most_common()),
            "liquidityBucket": dict(by_liq.most_common()),
            "marginBucket": dict(by_margin.most_common()),
            "sessionBucket": dict(by_session.most_common()),
            "signalType": dict(by_signal_type.most_common()),
        },
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-paper-trade-only-failure-factors.json"
        out_md = OUT / f"{args.date}-paper-trade-only-failure-factors.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {args.date} Paper Trade Only Failure Factors",
            "",
            f"- window: {start} .. {end} ({int(args.window_days)}d)",
            f"- sampleTrades: {total}",
            f"- lossCount(th<={loss_th:.2f}%): {loss_count}",
            f"- lossRate: {(loss_count/total*100):.1f}%" if total else "- lossRate: 0.0%",
            "",
            "## Top Factors",
            f"- creditStatus: {dict(by_credit.most_common(5))}",
            f"- liquidityBucket: {dict(by_liq.most_common(5))}",
            f"- marginBucket: {dict(by_margin.most_common(5))}",
            f"- sessionBucket: {dict(by_session.most_common(5))}",
            f"- signalType: {dict(by_signal_type.most_common(5))}",
        ]
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    write_pipeline_event(
        pipeline="investment_analysis",
        slot="inv-evening",
        stage="report_paper_trade_only_failure_factors",
        status="ok",
        event_date=args.date,
        return_code=0,
        payload=payload,
        source_path="scripts/investment/analysis/report_paper_trade_only_failure_factors.py",
    )
    print(
        "paper_trade_only_failure_factors date={0} sample={1} loss={2}".format(
            args.date, total, loss_count
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
