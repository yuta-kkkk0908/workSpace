#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "investment.db"
OUT = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze paper trade stats by rank/side/horizon")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--mode", default="backtest", choices=["backtest", "live", "all"])
    p.add_argument("--start-date")
    p.add_argument("--end-date")
    p.add_argument("--out-date", required=True, help="label date for output file")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        where = ["1=1"]
        params: list[object] = []
        if args.mode != "all":
            where.append("p.mode=?")
            params.append(args.mode)
        if args.start_date:
            where.append("p.entry_date>=?")
            params.append(args.start_date)
        if args.end_date:
            where.append("p.entry_date<=?")
            params.append(args.end_date)

        base_sql = f"""
            from paper_trades p
            left join signals s on s.date=p.entry_date and s.ticker=p.ticker
            where {' and '.join(where)}
        """

        rows = conn.execute(
            "select p.trade_id,p.entry_date,p.ticker,p.side,p.t1_return_pct,p.t5_return_pct,p.t20_return_pct,"
            "coalesce(s.long_rank,'') as long_rank,coalesce(s.short_rank,'') as short_rank "
            + base_sql,
            params,
        ).fetchall()
    finally:
        conn.close()

    def summarize(h: str):
        vals = [r[h] for r in rows if r[h] is not None]
        if not vals:
            return (0, 0, 0.0)
        wins = sum(1 for v in vals if v > 0)
        return (len(vals), wins, sum(vals) / len(vals))

    t1 = summarize("t1_return_pct")
    t5 = summarize("t5_return_pct")
    t20 = summarize("t20_return_pct")

    by_side: dict[str, list[float]] = {"long": [], "short": []}
    for r in rows:
        if r["t5_return_pct"] is not None:
            by_side[r["side"]].append(float(r["t5_return_pct"]))

    out = OUT / f"{args.out_date}-paper-trade-stats.md"
    lines = [
        f"# {args.out_date} Paper Trade Stats",
        "",
        "- caution: 仮想トレード検証。売買助言ではない。",
        f"- mode: {args.mode}",
        f"- sampleTrades: {len(rows)}",
        "",
        "## Horizon Summary",
        f"- T+1: n={t1[0]} winRate={(t1[1]/t1[0]*100 if t1[0] else 0):.1f}% avgRet={t1[2]:.2f}%",
        f"- T+5: n={t5[0]} winRate={(t5[1]/t5[0]*100 if t5[0] else 0):.1f}% avgRet={t5[2]:.2f}%",
        f"- T+20: n={t20[0]} winRate={(t20[1]/t20[0]*100 if t20[0] else 0):.1f}% avgRet={t20[2]:.2f}%",
        "",
        "## Side (T+5)",
    ]
    for side in ("long", "short"):
        vals = by_side[side]
        n = len(vals)
        wins = sum(1 for v in vals if v > 0)
        avg = sum(vals) / n if n else 0.0
        lines.append(f"- {side}: n={n} winRate={(wins/n*100 if n else 0):.1f}% avgRet={avg:.2f}%")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
