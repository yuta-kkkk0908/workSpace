#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_DB = ROOT / "data" / "investment.db"
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-unknown-priority-queue.md"


def importance(row: dict) -> int:
    score = 0
    if row["category"] == "unknown":
        score += 3
    if row["long_rank"] in {"A", "A-", "B+"}:
        score += 3
    if row["short_rank"] in {"A", "A-", "B", "B+"}:
        score += 3
    if row["outcome_type"] in {"failed_or_downtrend", "trend_continuation", "initial_pop_only"}:
        score += 2
    if row["expected_direction"] in {"up", "down"}:
        score += 1
    return score


def main() -> int:
    p = argparse.ArgumentParser(description="Prioritize unknown fields from DB.")
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(
            """
            SELECT ticker,signal_date,disclosure_category as category,signal_type,expected_direction,long_rank,short_rank,outcome_type,t1_judge,t5_judge,t20_judge
            FROM backtest_outcomes
            WHERE date=?
            """,
            (args.date,),
        ).fetchall()]
        filled_margin = {r[0] for r in conn.execute("SELECT ticker FROM margin_context_rows WHERE date=? AND COALESCE(margin_bucket,'')<>''", (args.date,)).fetchall()}
    finally:
        conn.close()
    category_unknown = [r for r in rows if (r.get("category") or "") == "unknown"]
    rank_priority = [r for r in rows if (r.get("long_rank") in {"A", "A-", "B+"} or r.get("short_rank") in {"A", "A-", "B", "B+"})]
    margin_unknown_priority = [r for r in rank_priority if r.get("ticker") not in filled_margin]
    category_unknown.sort(key=importance, reverse=True)
    margin_unknown_priority.sort(key=importance, reverse=True)
    out = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))
    lines = [
        f"# {args.date} Unknown Priority Queue",
        "",
        f"- outcomeRows: {len(rows)}",
        f"- disclosureCategoryUnknownRows: {len(category_unknown)}",
        f"- filledMarginTickers: {len(filled_margin)}",
        f"- rankPriorityRowsMissingMargin: {len(margin_unknown_priority)}",
        "",
        "## Priority 1",
    ]
    for r in category_unknown[:25]:
        lines.append(f"- {r.get('ticker','')} {r.get('signal_date','')}: category={r.get('category','')} type={r.get('signal_type','')} score={importance(r)}")
    lines.extend(["", "## Priority 2"])
    for r in margin_unknown_priority[:30]:
        lines.append(f"- {r.get('ticker','')} {r.get('signal_date','')}: long={r.get('long_rank','')} short={r.get('short_rank','')} score={importance(r)}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
