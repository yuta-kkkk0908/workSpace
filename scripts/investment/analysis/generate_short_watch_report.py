#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_DB = ROOT / "data" / "investment.db"
DEFAULT_OUTPUT = ROOT / "topics/investment-research/inbox/{date}-short-watch-report.md"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--output", type=Path, default=None)
    args = p.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT ticker,category,signal_type,short_rank,short_readiness,borrow_status,liquidity_bucket,t1,t5,t20
            FROM short_readiness_rows
            WHERE date=?
            ORDER BY ticker
            """,
            (args.date,),
        ).fetchall()
    finally:
        conn.close()
    out = args.output or Path(str(DEFAULT_OUTPUT).format(date=args.date))
    lines = [f"# {args.date} Short Watch Report", "", f"- rows: {len(rows)}", ""]
    for r in rows[:100]:
        lines.append(
            f"- {r['ticker']} {r['category'] or ''} / {r['signal_type'] or ''}: shortRank={r['short_rank'] or ''}, readiness={r['short_readiness'] or ''}, borrow={r['borrow_status'] or ''}, liquidity={r['liquidity_bucket'] or ''}, T+1/T+5/T+20={r['t1'] or ''}/{r['t5'] or ''}/{r['t20'] or ''}"
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
