#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_DB = ROOT / "data" / "investment.db"
OUTPUT_MD = ROOT / "topics/investment-research/inbox/{date}-short-chart-window-stats.md"
OUTPUT_JSON = ROOT / "topics/investment-research/inbox/{date}-short-chart-window-stats.json"


def win_rate(rows: list[dict], field: str) -> str:
    c = Counter((r.get(field) or "unknown") for r in rows)
    judged = c["win"] + c["loss"] + c["flat"]
    wr = c["win"] / judged * 100 if judged else 0.0
    return f"{c['win']}/{c['loss']}/{c['flat']} pending={c['pending']} wr={wr:.1f}%"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = p.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        src = conn.execute(
            """
            SELECT r.ticker,r.signal_date,r.signal_type,r.short_readiness,r.t1,r.t5,r.t20,
                   c.follow_through,c.rebound_risk
            FROM short_readiness_rows r
            LEFT JOIN short_chart_reviews c
              ON c.date=r.date AND c.ticker=r.ticker AND c.signal_date=r.signal_date AND c.signal_type=r.signal_type
            WHERE r.date=?
            """,
            (args.date,),
        ).fetchall()
    finally:
        conn.close()
    rows = [dict(r) for r in src]
    by_chart: dict[str, list[dict]] = defaultdict(list)
    by_readiness: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_chart[f"follow={r.get('follow_through') or 'unknown'} / rebound={r.get('rebound_risk') or 'unknown'}"].append(r)
        by_readiness[r.get("short_readiness") or "unknown"].append(r)
    out = {
        "date": args.date,
        "rows": len(rows),
        "byChart": {k: {"count": len(v)} for k, v in sorted(by_chart.items())},
        "byReadiness": {k: {"count": len(v)} for k, v in sorted(by_readiness.items())},
    }
    Path(str(OUTPUT_JSON).format(date=args.date)).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# {args.date} Short Chart Window Stats", "", f"- rows: {len(rows)}", "", "## By Chart"]
    for k, v in sorted(by_chart.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"- {k} ({len(v)}): T+1 {win_rate(v,'t1')} / T+5 {win_rate(v,'t5')} / T+20 {win_rate(v,'t20')}")
    Path(str(OUTPUT_MD).format(date=args.date)).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
