#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()
OUT = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Materialize signal_type aggressiveness rows from backtest outcomes")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=365, help="lookback calendar days")
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def _safe_mean(values: list[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _judge_win_rate(judges: list[str]) -> float:
    judged = [j for j in judges if j and j not in {"pending", "unjudged"}]
    if not judged:
        return 0.0
    return round(sum(1 for j in judged if "win" in j.lower()) / len(judged) * 100.0, 3)


def _direction_adjusted_return(expected_direction: str, raw_return: float | None) -> float | None:
    if raw_return is None:
        return None
    if expected_direction.lower() == "down":
        return round(-raw_return, 4)
    return round(raw_return, 4)


def _classify(sample_count: int, t5_wr: float, t5_avg: float | None, t20_avg: float | None) -> tuple[str, int, str]:
    if sample_count < 5:
        return "avoid", 0, "sample_count<5"
    if t5_avg is None:
        return "avoid", 0, "t5_avg_return_missing"
    if t5_wr < 47.0 or t5_avg < -0.25:
        return "avoid", 0, f"t5_winrate<{47.0:.1f} or t5_avg<{ -0.25:.2f}"
    if sample_count >= 20 and t5_wr >= 58.0 and t5_avg >= 0.60 and (t20_avg is not None and t20_avg >= 0.30):
        return "aggressive", 3, "sample>=20,t5_wr>=58.0,t5_avg>=0.60,t20_avg>=0.30"
    if sample_count >= 10 and t5_wr >= 54.0 and t5_avg >= 0.25 and (t20_avg is None or t20_avg >= 0.00):
        return "balanced", 2, "sample>=10,t5_wr>=54.0,t5_avg>=0.25,t20_avg>=0.00"
    if sample_count >= 5 and t5_wr >= 50.0 and t5_avg >= 0.00:
        return "conservative", 1, "sample>=5,t5_wr>=50.0,t5_avg>=0.00"
    return "avoid", 0, "thresholds_not_met"


def _load_rows(conn: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT signal_type,expected_direction,t1_judge,t5_judge,t20_judge,
               t1_close_vs_base_pct,t5_close_vs_base_pct,t20_close_vs_base_pct
        FROM backtest_outcomes
        WHERE signal_date BETWEEN ? AND ?
          AND COALESCE(signal_type,'')<>''
          AND COALESCE(expected_direction,'')<>''
        ORDER BY signal_type, expected_direction, signal_date
        """,
        (start, end),
    ).fetchall()


def _materialize(rows: list[sqlite3.Row], date: str, window_days: int) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], dict[str, list[float] | list[str] | int]] = defaultdict(lambda: {"t1": [], "t5": [], "t20": [], "judges_t1": [], "judges_t5": [], "judges_t20": [], "n": 0})
    for r in rows:
        signal_type = str(r["signal_type"] or "").strip()
        expected_direction = str(r["expected_direction"] or "").strip().lower()
        if not signal_type or expected_direction not in {"up", "down"}:
            continue
        bucket = grouped[(signal_type, expected_direction)]
        bucket["n"] = int(bucket["n"]) + 1
        bucket["judges_t1"].append(str(r["t1_judge"] or ""))  # type: ignore[index]
        bucket["judges_t5"].append(str(r["t5_judge"] or ""))  # type: ignore[index]
        bucket["judges_t20"].append(str(r["t20_judge"] or ""))  # type: ignore[index]
        t1 = _direction_adjusted_return(expected_direction, float(r["t1_close_vs_base_pct"]) if r["t1_close_vs_base_pct"] is not None else None)
        t5 = _direction_adjusted_return(expected_direction, float(r["t5_close_vs_base_pct"]) if r["t5_close_vs_base_pct"] is not None else None)
        t20 = _direction_adjusted_return(expected_direction, float(r["t20_close_vs_base_pct"]) if r["t20_close_vs_base_pct"] is not None else None)
        if t1 is not None:
            bucket["t1"].append(t1)  # type: ignore[index]
        if t5 is not None:
            bucket["t5"].append(t5)  # type: ignore[index]
        if t20 is not None:
            bucket["t20"].append(t20)  # type: ignore[index]

    results: list[dict[str, object]] = []
    for (signal_type, expected_direction), bucket in sorted(grouped.items(), key=lambda item: (-int(item[1]["n"]), item[0][0], item[0][1])):
        sample_count = int(bucket["n"])
        t1_wr = _judge_win_rate([str(x) for x in bucket["judges_t1"]])  # type: ignore[arg-type]
        t5_wr = _judge_win_rate([str(x) for x in bucket["judges_t5"]])  # type: ignore[arg-type]
        t20_wr = _judge_win_rate([str(x) for x in bucket["judges_t20"]])  # type: ignore[arg-type]
        t1_avg = _safe_mean([float(x) for x in bucket["t1"]])  # type: ignore[arg-type]
        t5_avg = _safe_mean([float(x) for x in bucket["t5"]])  # type: ignore[arg-type]
        t20_avg = _safe_mean([float(x) for x in bucket["t20"]])  # type: ignore[arg-type]
        level, score, reason = _classify(sample_count, t5_wr, t5_avg, t20_avg)
        results.append(
            {
                "date": date,
                "window_days": window_days,
                "signal_type": signal_type,
                "expected_direction": expected_direction,
                "sample_count": sample_count,
                "t1_win_rate_pct": t1_wr,
                "t5_win_rate_pct": t5_wr,
                "t20_win_rate_pct": t20_wr,
                "t1_dir_avg_return_pct": t1_avg,
                "t5_dir_avg_return_pct": t5_avg,
                "t20_dir_avg_return_pct": t20_avg,
                "aggressiveness_level": level,
                "aggressiveness_score": score,
                "decision_reason": reason,
                "source_path": "db:backtest_outcomes",
            }
        )
    return results


def _write_rows(conn: sqlite3.Connection, rows: list[dict[str, object]], date: str, window_days: int) -> None:
    conn.execute(
        "DELETE FROM signal_type_aggressiveness_rows WHERE date=? AND window_days=?",
        (date, window_days),
    )
    for row in rows:
        conn.execute(
            """
            INSERT INTO signal_type_aggressiveness_rows(
              date,window_days,signal_type,expected_direction,sample_count,
              t1_win_rate_pct,t5_win_rate_pct,t20_win_rate_pct,
              t1_dir_avg_return_pct,t5_dir_avg_return_pct,t20_dir_avg_return_pct,
              aggressiveness_level,aggressiveness_score,decision_reason,source_path,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(date,window_days,signal_type,expected_direction) DO UPDATE SET
              sample_count=excluded.sample_count,
              t1_win_rate_pct=excluded.t1_win_rate_pct,
              t5_win_rate_pct=excluded.t5_win_rate_pct,
              t20_win_rate_pct=excluded.t20_win_rate_pct,
              t1_dir_avg_return_pct=excluded.t1_dir_avg_return_pct,
              t5_dir_avg_return_pct=excluded.t5_dir_avg_return_pct,
              t20_dir_avg_return_pct=excluded.t20_dir_avg_return_pct,
              aggressiveness_level=excluded.aggressiveness_level,
              aggressiveness_score=excluded.aggressiveness_score,
              decision_reason=excluded.decision_reason,
              source_path=excluded.source_path,
              updated_at=excluded.updated_at
            """,
            (
                row["date"],
                row["window_days"],
                row["signal_type"],
                row["expected_direction"],
                row["sample_count"],
                row["t1_win_rate_pct"],
                row["t5_win_rate_pct"],
                row["t20_win_rate_pct"],
                row["t1_dir_avg_return_pct"],
                row["t5_dir_avg_return_pct"],
                row["t20_dir_avg_return_pct"],
                row["aggressiveness_level"],
                row["aggressiveness_score"],
                row["decision_reason"],
                row["source_path"],
            ),
        )
    conn.commit()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    start = (d0 - timedelta(days=max(1, int(args.window_days)) - 1)).isoformat()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _load_rows(conn, start, args.date)
        materialized = _materialize(rows, args.date, int(args.window_days))
        _write_rows(conn, materialized, args.date, int(args.window_days))
    finally:
        conn.close()

    payload = {
        "date": args.date,
        "window_days": int(args.window_days),
        "start": start,
        "end": args.date,
        "rows": materialized,
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-signal-type-aggressiveness.json"
        out_md = OUT / f"{args.date}-signal-type-aggressiveness.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {args.date} Signal Type Aggressiveness",
            "",
            f"- window_days: {int(args.window_days)}",
            f"- sample_period: {start} .. {args.date}",
            f"- rows: {len(materialized)}",
            "",
            "## Rules",
            "- aggressive: sample>=20 AND T+5 winRate>=58.0% AND T+5 dir avg return>=0.60% AND T+20 dir avg return>=0.30%",
            "- balanced: sample>=10 AND T+5 winRate>=54.0% AND T+5 dir avg return>=0.25% AND T+20 dir avg return>=0.00%",
            "- conservative: sample>=5 AND T+5 winRate>=50.0% AND T+5 dir avg return>=0.00%",
            "- avoid: sample<5 or T+5 winRate<47.0% or T+5 dir avg return<-0.25%",
            "",
            "## Summary",
        ]
        for row in materialized:
            lines.append(
                "- {signal_type} / {expected_direction}: n={sample_count} | T5 wr={t5_win_rate_pct:.1f}% avg={t5_dir_avg_return_pct} | T20 avg={t20_dir_avg_return_pct} | {aggressiveness_level}".format(
                    **row
                )
            )
        out_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    print(f"materialized_signal_type_aggressiveness rows={len(materialized)} date={args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
