#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill execution_plan rank/entry/tp/sl/rr/ev from DB context")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--start-date")
    p.add_argument("--end-date")
    p.add_argument("--take-profit-pct", type=float, default=4.0)
    p.add_argument("--stop-loss-pct", type=float, default=2.0)
    return p.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_winrate_text(text: str) -> float | None:
    m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def default_winrate_from_rank(rank: str) -> float:
    r = (rank or "").upper().strip()
    if r.startswith("A+"):
        return 60.0
    if r.startswith("A"):
        return 57.0
    if r.startswith("B+"):
        return 54.0
    if r.startswith("B"):
        return 52.0
    if r.startswith("C"):
        return 50.0
    return 49.0


def parse_wr_metric(text: str) -> float | None:
    return parse_winrate_text(text)


def compute_rr_ev(direction: str, entry: float | None, tp: float | None, sl: float | None, winrate_value: float | None) -> tuple[float | None, float | None]:
    if entry is None or tp is None or sl is None:
        return None, None
    if direction == "long":
        reward = tp - entry
        risk = entry - sl
    else:
        reward = entry - tp
        risk = sl - entry
    if risk <= 0:
        return None, None
    rr = reward / risk
    if winrate_value is None:
        return rr, None
    p = max(0.0, min(1.0, float(winrate_value) / 100.0))
    ev = p * reward - (1.0 - p) * risk
    return rr, ev


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        where = ["1=1"]
        params: list[object] = []
        if args.start_date:
            where.append("plan_date>=?")
            params.append(args.start_date)
        if args.end_date:
            where.append("plan_date<=?")
            params.append(args.end_date)
        rows = conn.execute(
            f"""
            SELECT plan_id,plan_date,ticker,direction,scenario_tier,rank,entry,tp,sl,rr,ev
            FROM execution_plan
            WHERE {' and '.join(where)}
            ORDER BY plan_date,plan_id
            """,
            params,
        ).fetchall()

        updated = 0
        side_wr_cache: dict[tuple[str, str], float | None] = {}
        for r in rows:
            plan_id = r["plan_id"]
            plan_date = r["plan_date"]
            ticker = str(r["ticker"] or "").strip()
            direction = str(r["direction"] or "long").strip().lower()
            scenario_tier = str(r["scenario_tier"] or "trade").strip()

            rank = str(r["rank"] or "").strip()
            entry = float(r["entry"]) if r["entry"] is not None else None
            tp = float(r["tp"]) if r["tp"] is not None else None
            sl = float(r["sl"]) if r["sl"] is not None else None

            if not rank:
                ec = conn.execute(
                    """
                    SELECT rank FROM entry_candidates
                    WHERE date=? AND ticker=? AND lower(side)=?
                    ORDER BY CASE WHEN candidate_type='primary' THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (plan_date, ticker, direction),
                ).fetchone()
                if ec and ec[0]:
                    rank = str(ec[0]).strip()
            if not rank:
                sig = conn.execute(
                    """
                    SELECT long_rank,short_rank FROM signals
                    WHERE date=? AND ticker=?
                    ORDER BY signal_id
                    LIMIT 1
                    """,
                    (plan_date, ticker),
                ).fetchone()
                if sig:
                    rank = str(sig[1] if direction == "short" else sig[0] or "").strip()

            if entry is None:
                px = conn.execute(
                    "SELECT close FROM facts_price_daily WHERE date=? AND ticker=?",
                    (plan_date, ticker),
                ).fetchone()
                if px and px[0] is not None:
                    entry = float(px[0])
            if entry is None:
                # fallback: most recent close before plan_date
                px_prev = conn.execute(
                    """
                    SELECT close
                    FROM facts_price_daily
                    WHERE ticker=?
                      AND date<?
                      AND close is not null
                    ORDER BY date DESC
                    LIMIT 1
                    """,
                    (ticker, plan_date),
                ).fetchone()
                if px_prev and px_prev[0] is not None:
                    entry = float(px_prev[0])
            if entry is not None and (tp is None or sl is None):
                tp_mult = 1.0 + (args.take_profit_pct / 100.0)
                sl_mult = 1.0 - (args.stop_loss_pct / 100.0)
                if direction == "long":
                    tp = tp if tp is not None else entry * tp_mult
                    sl = sl if sl is not None else entry * sl_mult
                else:
                    tp = tp if tp is not None else entry * (2.0 - tp_mult)
                    sl = sl if sl is not None else entry * (2.0 - sl_mult)

            wr_row = conn.execute(
                """
                SELECT estimated_winrate_value,estimated_winrate_text
                FROM opening_scenarios
                WHERE scenario_date=? AND ticker=? AND lower(direction)=? AND scenario_tier=?
                ORDER BY scenario_score DESC, scenario_index
                LIMIT 1
                """,
                (plan_date, ticker, direction, scenario_tier),
            ).fetchone()
            winrate = None
            if wr_row:
                if wr_row["estimated_winrate_value"] is not None:
                    try:
                        winrate = float(wr_row["estimated_winrate_value"])
                    except Exception:
                        winrate = None
                if winrate is None:
                    winrate = parse_winrate_text(str(wr_row["estimated_winrate_text"] or ""))
            if winrate is None:
                key = (plan_date, direction)
                if key not in side_wr_cache:
                    rr = conn.execute(
                        """
                        SELECT t5,t1
                        FROM rule_dashboard_rows
                        WHERE date<=? AND side=?
                        ORDER BY date DESC
                        LIMIT 1
                        """,
                        (plan_date, direction),
                    ).fetchone()
                    val = None
                    if rr:
                        val = parse_wr_metric(str(rr["t5"] or ""))
                        if val is None:
                            val = parse_wr_metric(str(rr["t1"] or ""))
                    side_wr_cache[key] = val
                winrate = side_wr_cache.get(key)
            if winrate is None:
                winrate = default_winrate_from_rank(rank)

            rr, ev = compute_rr_ev(direction, entry, tp, sl, winrate)
            if rr is None and r["rr"] is not None:
                rr = float(r["rr"])
            if ev is None and r["ev"] is not None:
                ev = float(r["ev"])

            changed = (
                rank != str(r["rank"] or "").strip()
                or entry != (float(r["entry"]) if r["entry"] is not None else None)
                or tp != (float(r["tp"]) if r["tp"] is not None else None)
                or sl != (float(r["sl"]) if r["sl"] is not None else None)
                or rr != (float(r["rr"]) if r["rr"] is not None else None)
                or ev != (float(r["ev"]) if r["ev"] is not None else None)
            )
            if not changed:
                continue
            conn.execute(
                """
                UPDATE execution_plan
                SET rank=?,entry=?,tp=?,sl=?,rr=?,ev=?,updated_at=?
                WHERE plan_id=?
                """,
                (rank, entry, tp, sl, rr, ev, now_iso(), plan_id),
            )
            updated += 1

        conn.commit()
    finally:
        conn.close()
    print(f"updated execution_plan rows={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
