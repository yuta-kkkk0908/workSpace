#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db
from utils.paper_trade_mode import normalize_paper_trade_mode

DEFAULT_DB = resolve_investment_db()
OUT = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build paper-trade status report")
    p.add_argument("--date", required=True, help="YYYY-MM-DD entry date")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--mode", default="paper_history", choices=["paper_history", "live", "all"])
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        mode = normalize_paper_trade_mode(args.mode)
        rows_mode = "all" if args.mode == "all" else mode
        if args.mode == "all":
            rows = conn.execute(
                """
                select trade_id,mode,entry_date,ticker,company,side,lots,status,
                       t1_return_pct,t5_return_pct,t20_return_pct,t1_judge,t5_judge,t20_judge
                from paper_trades
                where entry_date=?
                order by mode,ticker,side
                """,
                (args.date,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                select trade_id,mode,entry_date,ticker,company,side,lots,status,
                       t1_return_pct,t5_return_pct,t20_return_pct,t1_judge,t5_judge,t20_judge
                from paper_trades
                where entry_date=? and mode=?
                order by ticker,side
                """,
                (args.date, mode),
            ).fetchall()
    finally:
        conn.close()

    out = OUT / f"{args.date}-paper-trade-report.md"
    lines = [
        f"# {args.date} Paper Trade Report",
        "",
        "- caution: 仮想エントリーの検証記録。売買助言ではない。",
        f"- mode: {rows_mode}",
        f"- trades: {len(rows)}",
        "",
        "## Positions",
    ]
    if not rows:
        lines.append("- N/C")
    else:
        for r in rows:
            lines.extend(
                [
                    f"### {r['ticker']} {r['company']} [{r['side']}] x{r['lots']} ({r['mode']})",
                    f"- status: {r['status']}",
                    f"- T+1: return={r['t1_return_pct']}% / judge={r['t1_judge']}",
                    f"- T+5: return={r['t5_return_pct']}% / judge={r['t5_judge']}",
                    f"- T+20: return={r['t20_return_pct']}% / judge={r['t20_judge']}",
                    "",
                ]
            )
    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
