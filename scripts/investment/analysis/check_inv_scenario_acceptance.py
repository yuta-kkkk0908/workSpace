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
    p = argparse.ArgumentParser(description="Check D-1..D-3 acceptance for inv-scenario")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--unknown-rate-threshold", type=float, default=0.30)
    p.add_argument("--zero-streak-alert-days", type=int, default=2)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def _bool(x: bool) -> str:
    return "OK" if x else "NG"


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        # D-1: inv-scenario should finish without slot-level error.
        # When this checker runs inside the same slot execution, the final "slot done"
        # event may not exist yet. In that case, evaluate current-slot command errors
        # after the latest slot-start event for the date.
        row_start = conn.execute(
            """
            SELECT id
            FROM pipeline_events
            WHERE event_date=? AND slot='inv-scenario' AND stage='slot' AND status='start'
            ORDER BY id DESC
            LIMIT 1
            """,
            (args.date,),
        ).fetchone()
        start_id = int(row_start[0]) if row_start else 0

        row_done = conn.execute(
            """
            SELECT id,status
            FROM pipeline_events
            WHERE event_date=? AND slot='inv-scenario' AND stage='slot' AND status IN ('done','done_with_error')
            ORDER BY id DESC
            LIMIT 1
            """,
            (args.date,),
        ).fetchone()
        if row_done and int(row_done[0]) >= start_id > 0:
            slot_status = str(row_done[1])
            d1_ok = slot_status == "done"
        else:
            err_count = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM pipeline_events
                    WHERE event_date=? AND slot='inv-scenario' AND id>=? AND status='error'
                    """,
                    (args.date, start_id),
                ).fetchone()[0]
                or 0
            )
            slot_status = "in_progress"
            d1_ok = err_count == 0

        # D-2: scenario zero should not continue.
        d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
        streak = 0
        horizon = max(1, int(args.zero_streak_alert_days))
        daily_counts: list[dict[str, int | str]] = []
        for i in range(horizon):
            d = (d0 - timedelta(days=i)).isoformat()
            c = int(
                conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM opening_scenarios
                    WHERE scenario_date=? AND source_kind IN ('scenario','rejected')
                    """,
                    (d,),
                ).fetchone()[0]
                or 0
            )
            daily_counts.append({"date": d, "count": c})
            if c == 0:
                streak += 1
            else:
                break
        d2_ok = streak < horizon

        # D-3: unknown_rate should be below threshold.
        rows = conn.execute(
            """
            SELECT credit_status
            FROM credit_status_rows
            WHERE date=? AND source_kind LIKE 'auto_%'
            """,
            (args.date,),
        ).fetchall()
        auto_rows = len(rows)
        auto_unknown = sum(1 for r in rows if str((r[0] or "")).strip().lower() == "auto_unknown")
        unknown_rate = (auto_unknown / auto_rows) if auto_rows > 0 else 0.0
        d3_ok = unknown_rate < float(args.unknown_rate_threshold)
    finally:
        conn.close()

    overall_ok = d1_ok and d2_ok and d3_ok
    payload = {
        "date": args.date,
        "checks": {
            "D1_inv_scenario_exit0": d1_ok,
            "D2_no_continuous_zero_scenarios": d2_ok,
            "D3_unknown_rate_below_threshold": d3_ok,
        },
        "details": {
            "slotStatus": slot_status,
            "slotStartEventId": start_id,
            "zeroScenarioStreak": streak,
            "zeroScenarioAlertDays": horizon,
            "dailyScenarioCounts": daily_counts,
            "autoRows": auto_rows,
            "autoUnknown": auto_unknown,
            "unknownRate": round(unknown_rate, 4),
            "unknownRateThreshold": float(args.unknown_rate_threshold),
        },
        "overallStatus": "ok" if overall_ok else "degraded",
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-inv-scenario-acceptance.json"
        out_md = OUT / f"{args.date}-inv-scenario-acceptance.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {args.date} inv-scenario Acceptance",
            "",
            f"- D1 inv-scenario exit0: {_bool(d1_ok)}",
            f"- D2 no continuous zero scenarios: {_bool(d2_ok)}",
            f"- D3 unknown_rate < {float(args.unknown_rate_threshold):.2f}: {_bool(d3_ok)}",
            f"- overall: {payload['overallStatus']}",
            "",
            "## Details",
            f"- slotStatus: {payload['details']['slotStatus']}",
            f"- zeroScenarioStreak: {streak}",
            f"- autoRows: {auto_rows}",
            f"- autoUnknown: {auto_unknown}",
            f"- unknownRate: {unknown_rate:.3f}",
        ]
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    write_pipeline_event(
        pipeline="investment_analysis",
        slot="inv-scenario",
        stage="check_inv_scenario_acceptance",
        status="ok" if overall_ok else "degraded",
        event_date=args.date,
        return_code=0 if overall_ok else 1,
        payload=payload,
        source_path="scripts/investment/analysis/check_inv_scenario_acceptance.py",
    )
    print(
        "inv_scenario_acceptance date={0} D1={1} D2={2} D3={3} overall={4}".format(
            args.date, int(d1_ok), int(d2_ok), int(d3_ok), payload["overallStatus"]
        )
    )
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
