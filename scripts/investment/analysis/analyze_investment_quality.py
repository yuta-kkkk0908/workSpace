#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_DB = ROOT / "data" / "investment.db"
INBOX = ROOT / "topics/investment-research/inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Summarize investment quality from DB (DB-first).")
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def quality_label(score: float) -> str:
    if score >= 90:
        return "good"
    if score >= 70:
        return "usable_with_caution"
    if score >= 50:
        return "thin"
    return "weak"


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    try:
        signals = int(conn.execute("SELECT COUNT(*) FROM signals WHERE date=?", (args.date,)).fetchone()[0] or 0)
        entry_candidates = int(conn.execute("SELECT COUNT(*) FROM entry_candidates WHERE date=?", (args.date,)).fetchone()[0] or 0)
        opening_scenarios = int(conn.execute("SELECT COUNT(*) FROM opening_scenarios WHERE scenario_date=? AND source_kind='scenario'", (args.date,)).fetchone()[0] or 0)
        outcomes = int(conn.execute("SELECT COUNT(*) FROM backtest_outcomes WHERE date=?", (args.date,)).fetchone()[0] or 0)
        rule_rows = int(conn.execute("SELECT COUNT(*) FROM rule_dashboard_rows WHERE date=?", (args.date,)).fetchone()[0] or 0)
        unknown_expected = int(conn.execute("SELECT COUNT(*) FROM signals WHERE date=? AND (expected_direction='' OR expected_direction='unknown')", (args.date,)).fetchone()[0] or 0)
        unknown_rank = int(conn.execute("SELECT COUNT(*) FROM signals WHERE date=? AND (COALESCE(long_rank,'')='' OR COALESCE(short_rank,'')='')", (args.date,)).fetchone()[0] or 0)
    finally:
        conn.close()
    total_expected = max(1, signals * 2 + entry_candidates + opening_scenarios)
    total_unknown = unknown_expected + unknown_rank
    completeness = max(0.0, 100.0 - (total_unknown / total_expected * 100.0))
    report = {
        "date": args.date,
        "mode": "investment-quality-report",
        "createdAt": datetime.now(JST).replace(microsecond=0).isoformat(),
        "qualityLabel": quality_label(completeness),
        "completenessScore": round(completeness, 1),
        "rowCounts": {
            "signals": signals,
            "entry_candidates": entry_candidates,
            "opening_scenarios": opening_scenarios,
            "backtest_outcomes": outcomes,
            "rule_dashboard_rows": rule_rows,
        },
        "unknownCounts": {
            "signals.expected_direction_unknown": unknown_expected,
            "signals.rank_missing": unknown_rank,
        },
    }
    out_json = INBOX / f"{args.date}-quality-report.json"
    out_md = INBOX / f"{args.date}-quality-report.md"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(
        "\n".join(
            [
                f"# {args.date} Investment Quality Report",
                "",
                f"- qualityLabel: {report['qualityLabel']}",
                f"- completenessScore: {report['completenessScore']}",
                f"- signals: {signals}",
                f"- entry_candidates: {entry_candidates}",
                f"- opening_scenarios: {opening_scenarios}",
                f"- backtest_outcomes: {outcomes}",
                f"- rule_dashboard_rows: {rule_rows}",
                f"- unknown.expected_direction: {unknown_expected}",
                f"- unknown.rank_missing: {unknown_rank}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_md.relative_to(ROOT)} quality={report['qualityLabel']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
