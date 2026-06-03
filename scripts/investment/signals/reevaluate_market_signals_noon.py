#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Noon re-evaluation using intraday snapshots")
    p.add_argument("--date", required=True)
    p.add_argument("--slot", default="inv-noon")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


ORDER = ["C", "B", "A-", "A", "A+"]
NOON_ACTION_JA = {
    "ENTER": "新規エントリー",
    "ENTER_LIGHT": "軽めエントリー",
    "HOLD": "継続保有",
    "REDUCE": "縮小",
    "EXIT_WATCH": "撤退警戒",
}


def step_rank(rank: str, delta: int) -> str:
    r = (rank or "").strip().upper()
    if not r:
        r = "C"
    if r not in ORDER:
        return r
    i = max(0, min(len(ORDER) - 1, ORDER.index(r) + delta))
    return ORDER[i]


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT s.signal_id,s.ticker,s.expected_direction,s.long_rank,s.short_rank,s.gate_status,s.payload_json,
                   ms.vwap_gap_pct,ms.volume_ratio
            FROM signals s
            LEFT JOIN (
              SELECT m1.*
              FROM market_signal_snapshots m1
              JOIN (
                SELECT date,ticker,slot,MAX(snapshot_time) mx
                FROM market_signal_snapshots
                WHERE date=? AND slot=?
                GROUP BY date,ticker,slot
              ) m2
              ON m1.date=m2.date AND m1.ticker=m2.ticker AND m1.slot=m2.slot AND m1.snapshot_time=m2.mx
            ) ms
            ON ms.date=s.date AND ms.ticker=s.ticker
            WHERE s.date=?
            """,
            (args.date, args.slot, args.date),
        ).fetchall()
        adjusted = 0
        holded = 0
        for r in rows:
            lr = str(r["long_rank"] or "C")
            sr = str(r["short_rank"] or "C")
            exp = str(r["expected_direction"] or "").lower()
            gate = str(r["gate_status"] or "pass")
            vgap = float(r["vwap_gap_pct"]) if r["vwap_gap_pct"] is not None else None
            vr = float(r["volume_ratio"]) if r["volume_ratio"] is not None else None
            payload = {}
            try:
                payload = json.loads(str(r["payload_json"] or "") or "{}")
                if not isinstance(payload, dict):
                    payload = {}
            except Exception:
                payload = {}
            reasons: list[str] = []
            delta_long = 0
            delta_short = 0
            new_gate = gate
            morning_pos = str(payload.get("morningPositionStatus") or "not_entered").strip().lower()
            entered = morning_pos in {"entered", "open", "in_position", "yes", "true"}
            noon_action = "HOLD" if entered else "ENTER_LIGHT"
            no_add = False
            confidence = "low"

            # Gate: insufficient intraday evidence -> hold for evening recheck.
            if vgap is None or vr is None:
                new_gate = "hold_noon_recheck"
                reasons.append("NOON_SNAPSHOT_MISSING")
                noon_action = "EXIT_WATCH" if entered else "ENTER_LIGHT"
                confidence = "low"
            else:
                align_score = 0
                if exp.startswith("up"):
                    align_score = 1 if vgap >= 0.4 else (-1 if vgap <= -0.4 else 0)
                elif exp.startswith("down"):
                    align_score = 1 if vgap <= -0.4 else (-1 if vgap >= 0.4 else 0)
                vol_support = 1 if vr >= 0.35 else 0
                confidence = "high" if vr >= 0.8 else ("medium" if vr >= 0.35 else "low")

                # Gate: clear adverse move with participation.
                if exp.startswith("up") and vgap <= -1.0 and vr >= 0.5:
                    new_gate = "hold_noon_recheck"
                    reasons.append("NOON_ADVERSE_LONG")
                elif exp.startswith("down") and vgap >= 1.0 and vr >= 0.5:
                    new_gate = "hold_noon_recheck"
                    reasons.append("NOON_ADVERSE_SHORT")

                # Score: prioritize aligned move with volume follow-through.
                if exp.startswith("up"):
                    if vgap >= 0.5 and vr >= 0.35:
                        delta_long += 1
                        reasons.append("NOON_ALIGN_LONG")
                    elif vgap <= -0.7 and vr >= 0.35:
                        delta_long -= 1
                        reasons.append("NOON_COUNTER_LONG")
                elif exp.startswith("down"):
                    if vgap <= -0.5 and vr >= 0.35:
                        delta_short += 1
                        reasons.append("NOON_ALIGN_SHORT")
                    elif vgap >= 0.7 and vr >= 0.35:
                        delta_short -= 1
                        reasons.append("NOON_COUNTER_SHORT")

                if entered:
                    if align_score <= -1 and vr >= 0.5:
                        noon_action = "EXIT_WATCH"
                    elif align_score <= -1:
                        noon_action = "REDUCE"
                    else:
                        noon_action = "HOLD"
                    no_add = align_score <= 0
                else:
                    if align_score >= 1 and vol_support >= 1 and vr >= 0.8:
                        noon_action = "ENTER"
                    elif align_score >= 1:
                        noon_action = "ENTER_LIGHT"
                    else:
                        noon_action = "ENTER_LIGHT"
                        no_add = True
            nlr = step_rank(lr, delta_long)
            nsr = step_rank(sr, delta_short)
            changed = (nlr != lr or nsr != sr or new_gate != gate)
            payload["noonReeval"] = {
                "slot": args.slot,
                "vwapGapPct": vgap,
                "volumeRatio": vr,
                "reasonCodes": reasons,
                "oldGateStatus": gate,
                "newGateStatus": new_gate,
                "morningPositionStatus": morning_pos,
                "action": noon_action,
                "actionJa": NOON_ACTION_JA.get(noon_action, noon_action),
                "confidence": confidence,
                "noAdd": no_add,
            }
            if changed:
                adjusted += 1
            if new_gate == "hold_noon_recheck" and gate != "hold_noon_recheck":
                holded += 1
            conn.execute(
                """
                UPDATE signals
                SET long_rank=?, short_rank=?, gate_status=?, technical_signal_checked='yes',
                    payload_json=?, updated_at=datetime('now')
                WHERE date=? AND signal_id=?
                """,
                (nlr, nsr, new_gate, json.dumps(payload, ensure_ascii=False), args.date, str(r["signal_id"] or "")),
            )
        conn.commit()
    finally:
        conn.close()
    print(f"noon_reeval date={args.date} slot={args.slot} adjusted={adjusted}/{len(rows)} holded={holded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
