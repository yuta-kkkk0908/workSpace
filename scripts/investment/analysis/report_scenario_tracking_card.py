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
from utils.pipeline_events import write_pipeline_event

DEFAULT_DB = ROOT / "data" / "investment.db"
INBOX = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="One-page scenario tracking card")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=7)
    return p.parse_args()


def _pct(n: int, d: int) -> float:
    return (n / d) * 100.0 if d > 0 else 0.0


def _wr(bin_obj: dict) -> float:
    n = int(bin_obj.get("n", 0) or 0)
    w = int(bin_obj.get("win", 0) or 0)
    return _pct(w, n)


def _parse_reasons(raw: str | None) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    try:
        arr = json.loads(s)
    except Exception:
        return [s]
    if isinstance(arr, list):
        return [str(x) for x in arr if str(x or "").strip()]
    return [str(arr)]


def _is_data_quality_reason(r: str) -> bool:
    return (
        r in {"MATERIAL_NONE_TODAY", "NOON_DATA_GAP", "CREDIT_THIN"}
        or r.startswith("sampleCount<")
        or r.startswith("winRate_unknown")
    )


def load_supply_metrics(conn: sqlite3.Connection, start: str, end: str) -> dict:
    rows = conn.execute(
        """
        SELECT scenario_date, COUNT(*) AS posts, COUNT(DISTINCT ticker) AS unique_tickers
        FROM opening_scenarios
        WHERE scenario_date BETWEEN ? AND ?
          AND source_kind='scenario'
        GROUP BY scenario_date
        ORDER BY scenario_date
        """,
        (start, end),
    ).fetchall()
    by_day = {str(r["scenario_date"]): {"posts": int(r["posts"] or 0), "unique_tickers": int(r["unique_tickers"] or 0)} for r in rows}
    days = []
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = datetime.strptime(end, "%Y-%m-%d").date()
    d = d0
    while d <= d1:
        k = d.isoformat()
        v = by_day.get(k, {"posts": 0, "unique_tickers": 0})
        days.append({"date": k, **v})
        d += timedelta(days=1)
    total_days = len(days)
    zero_days = sum(1 for x in days if int(x["posts"]) <= 0)
    avg_posts = (sum(int(x["posts"]) for x in days) / total_days) if total_days > 0 else 0.0
    avg_unique = (sum(int(x["unique_tickers"]) for x in days) / total_days) if total_days > 0 else 0.0
    return {
        "days": days,
        "avg_posts": round(avg_posts, 3),
        "avg_unique_tickers": round(avg_unique, 3),
        "zero_day_count": zero_days,
        "zero_day_rate_pct": round(_pct(zero_days, total_days), 3),
    }


def load_data_quality_breakdown(conn: sqlite3.Connection, start: str, end: str) -> dict:
    rows = conn.execute(
        """
        SELECT reject_reasons_json
        FROM scenario_gate_diagnostics
        WHERE scenario_date BETWEEN ? AND ?
          AND gate_result='rejected'
        """,
        (start, end),
    ).fetchall()
    c = Counter()
    total = 0
    for r in rows:
        reasons = _parse_reasons(r["reject_reasons_json"])
        for x in reasons:
            if _is_data_quality_reason(x):
                c[x] += 1
                total += 1
    return {"total_hits": total, "reason_counts": dict(c)}


def load_kpi_snapshot(date_str: str) -> dict:
    p = INBOX / f"{date_str}-decision-support-kpi.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_payload(args: argparse.Namespace) -> dict:
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    start = (d0 - timedelta(days=max(1, int(args.window_days)) - 1)).isoformat()
    end = args.date

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        supply = load_supply_metrics(conn, start, end)
        dq = load_data_quality_breakdown(conn, start, end)
    finally:
        conn.close()

    kpi = load_kpi_snapshot(args.date)
    cohort = (kpi.get("kpi") or {}).get("cohort") or {}
    t5 = cohort.get("t5") or {}
    promoted = t5.get("promoted") or {}
    weak = t5.get("rejected_weak") or {}
    dq_rej = t5.get("rejected_data_quality") or {}
    gap_weak = round(_wr(weak) - _wr(promoted), 3)
    gap_dq = round(_wr(dq_rej) - _wr(promoted), 3)
    tech = (kpi.get("kpi") or {}).get("technical_t5") or {}

    decision = "KEEP"
    min_n = min(int(promoted.get("n", 0) or 0), int(weak.get("n", 0) or 0))
    if min_n >= 20:
        if gap_weak >= 3.0:
            decision = "RELAX"
        elif gap_weak <= -5.0:
            decision = "TIGHTEN"

    return {
        "date": args.date,
        "window": {"start": start, "end": end, "days": int(args.window_days)},
        "decision": decision,
        "supply": supply,
        "cohort_t5": {
            "promoted": promoted,
            "rejected_weak": weak,
            "rejected_data_quality": dq_rej,
            "gap_weak_minus_promoted_pt": gap_weak,
            "gap_data_quality_minus_promoted_pt": gap_dq,
        },
        "data_quality_reject_breakdown": dq,
        "technical_t5": tech,
    }


def render_md(payload: dict) -> str:
    w = payload["window"]
    s = payload["supply"]
    c = payload["cohort_t5"]
    dq = payload["data_quality_reject_breakdown"]
    lines = [
        f"# {payload['date']} Scenario Tracking Card",
        "",
        f"- window: {w['start']} .. {w['end']} ({w['days']}d)",
        f"- decision: {payload['decision']}",
        "",
        "## Supply",
        f"- avg opening_scenarios/day: {s['avg_posts']}",
        f"- avg unique_tickers/day: {s['avg_unique_tickers']}",
        f"- zero-day: {s['zero_day_count']} / {len(s['days'])} ({s['zero_day_rate_pct']:.1f}%)",
        "",
        "## Cohort T+5",
        f"- promoted: n={int(c['promoted'].get('n',0) or 0)} winRate={_wr(c['promoted']):.1f}%",
        f"- rejected_weak: n={int(c['rejected_weak'].get('n',0) or 0)} winRate={_wr(c['rejected_weak']):.1f}% gap={c['gap_weak_minus_promoted_pt']:+.1f}pt",
        f"- rejected_data_quality: n={int(c['rejected_data_quality'].get('n',0) or 0)} winRate={_wr(c['rejected_data_quality']):.1f}% gap={c['gap_data_quality_minus_promoted_pt']:+.1f}pt",
        "",
        "## Data Quality Reject Reasons",
        f"- total reason hits: {dq['total_hits']}",
    ]
    rc = dq.get("reason_counts") or {}
    if rc:
        for k, v in sorted(rc.items(), key=lambda kv: kv[1], reverse=True)[:12]:
            lines.append(f"- {k}: {v}")
    else:
        lines.append("- none")

    lines.extend(["", "## Technical Tags T+5 (Top)"])
    for cohort_name in ("promoted", "rejected_weak", "rejected_data_quality"):
        lines.append(f"- {cohort_name}:")
        items = sorted(((payload.get("technical_t5") or {}).get(cohort_name) or {}).items(), key=lambda kv: int(kv[1].get("n", 0) or 0), reverse=True)
        if not items:
            lines.append("  - none")
            continue
        for tag, rec in items[:8]:
            n = int(rec.get("n", 0) or 0)
            wr = _pct(int(rec.get("win", 0) or 0), n) if n > 0 else 0.0
            lines.append(f"  - {tag}: n={n} wr={wr:.1f}%")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    payload = build_payload(args)
    out_json = INBOX / f"{args.date}-scenario-tracking-card.json"
    out_md = INBOX / f"{args.date}-scenario-tracking-card.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_md(payload), encoding="utf-8")
    print(f"wrote {out_md.relative_to(ROOT)}")
    print(f"wrote {out_json.relative_to(ROOT)}")
    write_pipeline_event(
        pipeline="investment_analysis",
        slot="inv-scenario",
        stage="report_scenario_tracking_card",
        status="ok",
        event_date=args.date,
        return_code=0,
        payload=payload,
        source_path="scripts/investment/analysis/report_scenario_tracking_card.py",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

