#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Nightly technical check and rank re-evaluation for market-signals (DB-first)")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--fallback-days", type=int, default=3)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def tokens(signal_type: str) -> set[str]:
    parts = [p.strip() for p in re.split(r"\s*/\s*|\s*,\s*", signal_type or "") if p.strip()]
    return {p.lower() for p in parts}


def rerank(row: dict[str, str]) -> tuple[str, str, str, str, bool]:
    signal_type = row.get("signal_type", "")
    expected = (row.get("expected_direction", "") or "").lower()
    gate = (row.get("gate_status", "") or "").lower()
    material = (row.get("material_signal_checked", "") or "").lower()
    external = (row.get("external_context_checked", "") or "").lower()
    lr = row.get("long_rank", "") or "C"
    sr = row.get("short_rank", "") or "C"
    tk = tokens(signal_type)
    upgraded = False
    reason = "neutral"

    if expected.startswith("up"):
        if "technical_breakout" in tk:
            reason = "breakout"
            if lr in {"B", "B+"}:
                lr = "A-"
                upgraded = True
        elif "relative_strength" in tk and gate == "pass":
            reason = "relative_strength"
    elif expected.startswith("down"):
        if "technical_breakdown" in tk:
            reason = "breakdown"
            if sr in {"B", "B+"}:
                sr = "A-"
                upgraded = True
        elif "sell_the_news" in tk and gate == "pass" and external == "yes":
            reason = "sell_the_news"

    if material == "yes" and external == "yes" and gate == "pass":
        if expected.startswith("up") and lr == "B" and {"earnings_positive", "self_buyback"} & tk:
            lr = "A-"
            upgraded = True
            reason = "material+confirmation"
        if expected.startswith("down") and sr == "B" and {"earnings_negative"} & tk:
            sr = "A-"
            upgraded = True
            reason = "material+confirmation"

    signal_rank = "B"
    if "A" in lr or "A" in sr:
        signal_rank = "A-"
    elif lr.startswith("C") and sr.startswith("C"):
        signal_rank = "C"
    return lr, sr, signal_rank, reason, upgraded


def find_target_date(conn: sqlite3.Connection, date_str: str, fallback_days: int) -> str | None:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        n = conn.execute("SELECT COUNT(*) FROM signals WHERE date=?", (d,)).fetchone()[0]
        if n and int(n) > 0:
            return d
    return None


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        target = find_target_date(conn, args.date, args.fallback_days)
        if not target:
            raise SystemExit(f"signals not found in DB for {args.date} (fallback_days={args.fallback_days})")
        rows = conn.execute(
            """
            SELECT signal_id,signal_type,expected_direction,long_rank,short_rank,gate_status,
                   material_signal_checked,external_context_checked
            FROM signals
            WHERE date=?
            ORDER BY signal_id
            """,
            (target,),
        ).fetchall()
        if not rows:
            print(f"no signal rows: {target}")
            return 0
        upgraded = 0
        for r in rows:
            d = dict(r)
            lr, sr, signal_rank, reason, up = rerank(d)
            if up:
                upgraded += 1
            conn.execute(
                """
                UPDATE signals
                SET long_rank=?, short_rank=?, technical_signal_checked='yes', updated_at=datetime('now')
                WHERE date=? AND signal_id=?
                """,
                (lr, sr, target, d.get("signal_id", "")),
            )
        conn.commit()
    finally:
        conn.close()
    print(f"updated db: date={target} upgraded={upgraded}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
