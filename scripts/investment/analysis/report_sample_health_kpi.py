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
    p = argparse.ArgumentParser(description="Report pending ratio and effective sample KPI")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--min-effective-sample", type=int, default=3)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def _ratio(n: int, d: int) -> float:
    return (n / d) if d > 0 else 0.0


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
            SELECT t1_judge,t5_judge,t20_judge
            FROM backtest_outcomes
            WHERE date BETWEEN ? AND ?
            """,
            (start, end),
        ).fetchall()
        total = len(rows)
        pending_like = {"", "pending", "unjudged"}
        judged_any = 0
        pending_all = 0
        for r in rows:
            vals = [str(r["t1_judge"] or "").strip().lower(), str(r["t5_judge"] or "").strip().lower(), str(r["t20_judge"] or "").strip().lower()]
            if all(v in pending_like for v in vals):
                pending_all += 1
            if any(v not in pending_like for v in vals):
                judged_any += 1

        tier_rows = conn.execute(
            """
            SELECT payload_json
            FROM scenario_gate_diagnostics
            WHERE scenario_date BETWEEN ? AND ?
              AND gate_result='accepted'
            """,
            (start, end),
        ).fetchall()
        accepted = 0
        effective = 0
        for (raw,) in tier_rows:
            if not raw:
                continue
            try:
                p = json.loads(str(raw))
            except Exception:
                continue
            if not isinstance(p, dict):
                continue
            accepted += 1
            n = int(p.get("ruleSampleCount") or 0)
            if n >= int(args.min_effective_sample):
                effective += 1
    finally:
        conn.close()

    pending_ratio = _ratio(pending_all, total)
    judged_ratio = _ratio(judged_any, total)
    effective_ratio = _ratio(effective, accepted)

    payload = {
        "date": args.date,
        "windowDays": int(args.window_days),
        "windowStart": start,
        "windowEnd": end,
        "kpi": {
            "outcomesTotal": total,
            "outcomesPendingAll": pending_all,
            "outcomesJudgedAny": judged_any,
            "pendingAllRatio": round(pending_ratio, 4),
            "judgedAnyRatio": round(judged_ratio, 4),
            "acceptedScenarios": accepted,
            "effectiveSampleThreshold": int(args.min_effective_sample),
            "effectiveSampleCount": effective,
            "effectiveSampleRatio": round(effective_ratio, 4),
        },
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-sample-health-kpi.json"
        out_md = OUT / f"{args.date}-sample-health-kpi.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {args.date} Sample Health KPI",
            "",
            f"- window: {start} .. {end} ({int(args.window_days)}d)",
            f"- outcomesTotal: {total}",
            f"- pendingAll: {pending_all} ({pending_ratio:.1%})",
            f"- judgedAny: {judged_any} ({judged_ratio:.1%})",
            f"- acceptedScenarios: {accepted}",
            f"- effectiveSample(>={int(args.min_effective_sample)}): {effective} ({effective_ratio:.1%})",
        ]
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    write_pipeline_event(
        pipeline="investment_analysis",
        slot="inv-scenario",
        stage="report_sample_health_kpi",
        status="ok",
        event_date=args.date,
        return_code=0,
        payload=payload,
        source_path="scripts/investment/analysis/report_sample_health_kpi.py",
    )
    print(
        "sample_health_kpi date={0} pending={1:.3f} judged={2:.3f} effective={3:.3f}".format(
            args.date, pending_ratio, judged_ratio, effective_ratio
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

