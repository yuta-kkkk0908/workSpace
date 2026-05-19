#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Replay current entry gate on past signals (DB-primary).")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--from-date", required=True)
    p.add_argument("--to-date", required=True)
    p.add_argument("--min-rule-hits", type=int, default=3)
    p.add_argument("--min-score", type=int, default=62)
    return p.parse_args()


def rule_hits(sig: sqlite3.Row) -> int:
    hits = 0
    if (sig["gate_status"] or "").lower() == "pass":
        hits += 1
    rank = (sig["long_rank"] if (sig["expected_direction"] or "").startswith("up") else sig["short_rank"]) or ""
    rank = rank.upper()
    if rank.startswith("A"):
        hits += 2
    elif rank.startswith("B"):
        hits += 1
    return hits


def score(sig: sqlite3.Row, hits: int) -> int:
    s = 45 + min(hits, 5) * 8
    rank = (sig["long_rank"] if (sig["expected_direction"] or "").startswith("up") else sig["short_rank"]) or ""
    if rank.upper().startswith("A"):
        s += 12
    elif rank.upper().startswith("B"):
        s += 6
    return max(0, min(100, s))


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sigs = cur.execute(
        """
        SELECT signal_id,date,ticker,expected_direction,long_rank,short_rank,gate_status
        FROM signals
        WHERE date BETWEEN ? AND ?
        ORDER BY date, signal_id
        """,
        (args.from_date, args.to_date),
    ).fetchall()

    accepted = []
    for s in sigs:
        h = rule_hits(s)
        sc = score(s, h)
        if h >= args.min_rule_hits and sc >= args.min_score:
            accepted.append((s["signal_id"], s["date"], s["expected_direction"]))

    wins = losses = flats = 0
    for sid, _, direction in accepted:
        row = cur.execute(
            """
            SELECT t5_judge
            FROM backtest_outcomes
            WHERE source_signal_id=?
            ORDER BY COALESCE(updated_at,'') DESC
            LIMIT 1
            """,
            (sid,),
        ).fetchone()
        if not row:
            continue
        j = (row["t5_judge"] or "").lower()
        if j == "win":
            wins += 1
        elif j == "loss":
            losses += 1
        elif j == "flat":
            flats += 1

    judged = wins + losses + flats
    wr = (wins / judged * 100.0) if judged else 0.0
    print(f"period={args.from_date}..{args.to_date}")
    print(f"signals={len(sigs)} accepted={len(accepted)} accepted_rate={(len(accepted)/len(sigs)*100.0 if sigs else 0):.1f}%")
    print(f"t5 judged={judged} win={wins} loss={losses} flat={flats} win_rate={wr:.1f}%")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

