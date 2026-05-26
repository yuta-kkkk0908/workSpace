#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
OUT_DIR = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate technical signal performance (T+1/T+5) on recent trading days")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out-date", required=True)
    p.add_argument("--window-days", type=int, default=30, help="recent trading days window")
    p.add_argument("--min-samples", type=int, default=5)
    return p.parse_args()


def pct(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def wr(values: list[float]) -> float:
    return round(sum(1 for v in values if v > 0) / len(values) * 100.0, 1) if values else 0.0


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        trade_days = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM facts_price_daily ORDER BY date DESC LIMIT ?",
                (args.window_days,),
            ).fetchall()
        ]
        if not trade_days:
            raise SystemExit("facts_price_daily is empty")
        min_day = trade_days[-1]
        max_day = trade_days[0]

        rows = conn.execute(
            """
            WITH sig AS (
              SELECT signal_id,date,ticker,signal_type,expected_direction
              FROM signals
              WHERE source='technical_daily'
                AND date BETWEEN ? AND ?
            )
            SELECT
              s.signal_id,
              s.date as signal_date,
              s.ticker,
              s.signal_type,
              s.expected_direction,
              p0.close as c0,
              (
                SELECT p1.close FROM facts_price_daily p1
                WHERE p1.ticker=s.ticker AND p1.date > s.date
                ORDER BY p1.date
                LIMIT 1 OFFSET 0
              ) as c1,
              (
                SELECT p5.close FROM facts_price_daily p5
                WHERE p5.ticker=s.ticker AND p5.date > s.date
                ORDER BY p5.date
                LIMIT 1 OFFSET 4
              ) as c5
            FROM sig s
            JOIN facts_price_daily p0
              ON p0.ticker=s.ticker AND p0.date=s.date
            """,
            (min_day, max_day),
        ).fetchall()
    finally:
        conn.close()

    by_type: dict[str, dict[str, list[float] | int]] = {}
    detail_rows: list[dict[str, object]] = []
    for r in rows:
        c0 = r["c0"]
        c1 = r["c1"]
        c5 = r["c5"]
        if c0 is None or c1 is None or c5 is None:
            continue
        t1 = (float(c1) - float(c0)) / float(c0) * 100.0
        t5 = (float(c5) - float(c0)) / float(c0) * 100.0
        st = str(r["signal_type"] or "unknown")
        by_type.setdefault(st, {"t1": [], "t5": [], "n": 0})
        by_type[st]["t1"].append(t1)  # type: ignore[index]
        by_type[st]["t5"].append(t5)  # type: ignore[index]
        by_type[st]["n"] = int(by_type[st]["n"]) + 1  # type: ignore[index]
        detail_rows.append(
            {
                "signal_id": r["signal_id"],
                "signal_date": r["signal_date"],
                "ticker": r["ticker"],
                "signal_type": st,
                "expected_direction": r["expected_direction"],
                "t1_ret_pct": round(t1, 4),
                "t5_ret_pct": round(t5, 4),
            }
        )

    summary = []
    for st, d in sorted(by_type.items(), key=lambda x: int(x[1]["n"]), reverse=True):
        n = int(d["n"])
        t1_vals = d["t1"]  # type: ignore[assignment]
        t5_vals = d["t5"]  # type: ignore[assignment]
        summary.append(
            {
                "signal_type": st,
                "samples": n,
                "t1_wr": wr(t1_vals),  # type: ignore[arg-type]
                "t1_avg_ret": pct(t1_vals),  # type: ignore[arg-type]
                "t5_wr": wr(t5_vals),  # type: ignore[arg-type]
                "t5_avg_ret": pct(t5_vals),  # type: ignore[arg-type]
                "verdict": "insufficient" if n < args.min_samples else ("promote_candidate" if wr(t5_vals) >= 55.0 and pct(t5_vals) >= 0.15 else "watch_more"),  # type: ignore[arg-type]
            }
        )

    out_md = OUT_DIR / f"{args.out_date}-technical-signal-performance.md"
    out_json = OUT_DIR / f"{args.out_date}-technical-signal-performance.json"
    lines = [
        f"# {args.out_date} Technical Signal Performance",
        "",
        f"- window_trading_days: {args.window_days}",
        f"- sample_period: {min_day} .. {max_day}",
        f"- total_samples: {len(detail_rows)}",
        f"- min_samples: {args.min_samples}",
        "",
        "## Summary",
    ]
    if not summary:
        lines.append("- no samples")
    else:
        for s in summary:
            lines.append(
                f"- {s['signal_type']}: n={s['samples']} | T+1 wr={s['t1_wr']}% avg={s['t1_avg_ret']}% | T+5 wr={s['t5_wr']}% avg={s['t5_avg_ret']}% | {s['verdict']}"
            )
    out_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    out_json.write_text(
        json.dumps(
            {
                "out_date": args.out_date,
                "window_trading_days": args.window_days,
                "sample_period": {"min_day": min_day, "max_day": max_day},
                "summary": summary,
                "samples": detail_rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out_md.relative_to(ROOT)}")
    print(f"wrote {out_json.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
