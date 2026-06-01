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
    p = argparse.ArgumentParser(description="Report 2-week trend of sampleCount>=3 ratio")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=14)
    p.add_argument("--min-sample-for-trade", type=int, default=3)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def _safe_ratio(n: int, d: int) -> float:
    return (n / d) if d > 0 else 0.0


def main() -> int:
    args = parse_args()
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    dates = [(d0 - timedelta(days=i)).isoformat() for i in range(max(1, int(args.window_days)))]
    dates = list(reversed(dates))

    conn = sqlite3.connect(args.db)
    try:
        daily: list[dict] = []
        for ds in dates:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM scenario_gate_diagnostics
                WHERE scenario_date=?
                  AND gate_result='accepted'
                """,
                (ds,),
            ).fetchall()
            total = 0
            strong = 0
            for (raw,) in rows:
                if not raw:
                    continue
                try:
                    p = json.loads(str(raw))
                except Exception:
                    continue
                if not isinstance(p, dict):
                    continue
                total += 1
                n = int(p.get("ruleSampleCount") or 0)
                if n >= int(args.min_sample_for_trade):
                    strong += 1
            ratio = _safe_ratio(strong, total)
            daily.append(
                {
                    "date": ds,
                    "accepted": total,
                    "sampleCountGeThreshold": strong,
                    "ratio": round(ratio, 4),
                }
            )
    finally:
        conn.close()

    mid = max(1, len(daily) // 2)
    first = daily[:mid]
    second = daily[mid:]
    first_ratio = _safe_ratio(sum(int(x["sampleCountGeThreshold"]) for x in first), sum(int(x["accepted"]) for x in first))
    second_ratio = _safe_ratio(sum(int(x["sampleCountGeThreshold"]) for x in second), sum(int(x["accepted"]) for x in second))
    trend_delta = round(second_ratio - first_ratio, 4)
    trend_up = trend_delta > 0

    payload = {
        "date": args.date,
        "windowDays": int(args.window_days),
        "minSampleForTrade": int(args.min_sample_for_trade),
        "daily": daily,
        "summary": {
            "firstHalfRatio": round(first_ratio, 4),
            "secondHalfRatio": round(second_ratio, 4),
            "trendDelta": trend_delta,
            "trendUp": trend_up,
        },
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-samplecount-trade-trend.json"
        out_md = OUT / f"{args.date}-samplecount-trade-trend.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {args.date} SampleCount Trade Trend",
            "",
            "- policy: 本レポートは昇格判断の提案情報であり、自動発注は前提にしない",
            f"- windowDays: {int(args.window_days)}",
            f"- minSampleForTrade: {int(args.min_sample_for_trade)}",
            f"- firstHalfRatio: {first_ratio:.1%}",
            f"- secondHalfRatio: {second_ratio:.1%}",
            f"- trendDelta: {trend_delta:+.1%}",
            f"- trendUp: {'yes' if trend_up else 'no'}",
            "",
            "## Daily",
        ]
        for d in daily:
            lines.append(
                f"- {d['date']}: accepted={d['accepted']} / sampleCount>={int(args.min_sample_for_trade)}={d['sampleCountGeThreshold']} / ratio={float(d['ratio']):.1%}"
            )
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    write_pipeline_event(
        pipeline="investment_analysis",
        slot="inv-scenario",
        stage="report_samplecount_trade_trend",
        status="ok",
        event_date=args.date,
        return_code=0,
        payload=payload,
        source_path="scripts/investment/analysis/report_samplecount_trade_trend.py",
    )
    print(
        "samplecount_trade_trend date={0} first={1:.3f} second={2:.3f} delta={3:+.3f}".format(
            args.date, first_ratio, second_ratio, trend_delta
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
