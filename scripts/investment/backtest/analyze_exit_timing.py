#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
OUT = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analyze practical exit timing hints from paper_trades")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--mode", default="all", choices=["backtest", "live", "watch", "paper", "all"])
    p.add_argument("--start-date")
    p.add_argument("--end-date")
    p.add_argument("--out-date", required=True)
    return p.parse_args()


def win_rate(vals: list[float]) -> float:
    if not vals:
        return 0.0
    return sum(1 for v in vals if v > 0) / len(vals) * 100.0


def avg(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        where = ["1=1"]
        params: list[object] = []
        if args.mode != "all":
            where.append("mode=?")
            params.append(args.mode)
        if args.start_date:
            where.append("entry_date>=?")
            params.append(args.start_date)
        if args.end_date:
            where.append("entry_date<=?")
            params.append(args.end_date)
        rows = conn.execute(
            """
            select trade_id,mode,entry_date,ticker,company,side,status,
                   t1_return_pct,t5_return_pct,t20_return_pct
            from paper_trades
            where """
            + " and ".join(where)
            + " order by entry_date,ticker",
            params,
        ).fetchall()
    finally:
        conn.close()

    def horizon_vals(target_rows: list[sqlite3.Row], key: str) -> list[float]:
        return [float(r[key]) for r in target_rows if r[key] is not None]

    def best_horizon(target_rows: list[sqlite3.Row]) -> tuple[str, float]:
        t1 = horizon_vals(target_rows, "t1_return_pct")
        t5 = horizon_vals(target_rows, "t5_return_pct")
        t20 = horizon_vals(target_rows, "t20_return_pct")
        best = "T+1"
        best_wr = win_rate(t1)
        if win_rate(t5) > best_wr:
            best = "T+5"
            best_wr = win_rate(t5)
        if win_rate(t20) > best_wr:
            best = "T+20"
            best_wr = win_rate(t20)
        return best, best_wr

    def append_mode_block(lines: list[str], label: str, target_rows: list[sqlite3.Row]) -> None:
        t1 = horizon_vals(target_rows, "t1_return_pct")
        t5 = horizon_vals(target_rows, "t5_return_pct")
        t20 = horizon_vals(target_rows, "t20_return_pct")
        best, _ = best_horizon(target_rows)
        lines.extend(
            [
                f"### {label}",
                f"- samples: {len(target_rows)}",
                f"- T+1: n={len(t1)} winRate={win_rate(t1):.1f}% avgRet={avg(t1):.2f}%",
                f"- T+5: n={len(t5)} winRate={win_rate(t5):.1f}% avgRet={avg(t5):.2f}%",
                f"- T+20: n={len(t20)} winRate={win_rate(t20):.1f}% avgRet={avg(t20):.2f}%",
                f"- suggested: {best}",
                "",
            ]
        )

    out = OUT / f"{args.out_date}-paper-trade-exit-timing.md"
    lines = [
        f"# {args.out_date} Paper Trade Exit Timing",
        "",
        "- caution: 仮想トレード統計に基づく保有期間の目安。売買助言ではない。",
        f"- mode: {args.mode}",
        f"- samples: {len(rows)}",
        "",
    ]
    if args.mode == "all":
        lines.extend(["## Mode Comparison", ""])
        for m in ("backtest", "watch", "live", "paper"):
            append_mode_block(lines, m, [r for r in rows if r["mode"] == m])
        lines.extend(["## Combined", ""])
        append_mode_block(lines, "all", rows)
    else:
        lines.extend(["## Horizon Metrics", ""])
        append_mode_block(lines, args.mode, rows)
        lines.extend(
            [
                "## Suggested Default Exit Window",
                f"- 優先候補: {best_horizon(rows)[0]}（観測上 winRate が最大）",
                "- 補足: 実運用ではボラティリティ、地合い、イベント日程で前倒し/延長する。",
            ]
        )
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
