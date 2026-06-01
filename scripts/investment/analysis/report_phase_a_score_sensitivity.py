#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"
DEFAULT_OUT = ROOT / "topics" / "investment-research" / "inbox" / "{date}-phase-a-score-sensitivity.md"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Report Phase-A score sensitivity against backtest outcomes")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--window-days", type=int, default=90)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out", type=Path, default=None)
    return p.parse_args()


def win01(v: str | None) -> int | None:
    s = str(v or "").strip().lower()
    if s == "win":
        return 1
    if s in {"loss", "flat"}:
        return 0
    return None


def pct(x: int, n: int) -> float:
    if n <= 0:
        return 0.0
    return (x / n) * 100.0


def bucket(score: int) -> str:
    if score >= 85:
        return "85+"
    if score >= 75:
        return "75-84"
    if score >= 65:
        return "65-74"
    return "<65"


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    d1 = (d0 - timedelta(days=max(1, int(args.window_days)) - 1)).isoformat()
    out = args.out or Path(str(DEFAULT_OUT).format(date=args.date))

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT sg.scenario_date,sg.signal_id,sg.ticker,sg.direction,sg.gate_result,sg.payload_json,
                   bo.t5_judge,bo.t20_judge
            FROM scenario_gate_diagnostics sg
            LEFT JOIN backtest_outcomes bo
              ON bo.source_signal_id = sg.signal_id
             AND bo.ticker = sg.ticker
            WHERE sg.scenario_date BETWEEN ? AND ?
              AND sg.gate_result='accepted'
            """,
            (d1, args.date),
        ).fetchall()
    finally:
        conn.close()

    score_bins: dict[str, dict[str, int]] = {}
    factor_bins: dict[str, dict[str, int]] = {}
    evaluated = 0
    for r in rows:
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except Exception:
            payload = {}
        sb = payload.get("scoreBreakdown") or {}
        total = int(payload.get("scenarioScore") or 0)
        t5 = win01(r["t5_judge"])
        t20 = win01(r["t20_judge"])
        if t5 is None and t20 is None:
            continue
        y = t5 if t5 is not None else t20
        evaluated += 1

        b = bucket(total)
        rec = score_bins.setdefault(b, {"n": 0, "win": 0})
        rec["n"] += 1
        rec["win"] += int(y)

        for key in (
            "phase_a_material",
            "phase_a_market",
            "phase_a_volatility",
            "phase_a_gap",
            "phase_b_market_regime",
            "phase_b_sector_regime",
        ):
            val = int(sb.get(key, 0) or 0)
            tag = f"{key}:{'high' if val >= 3 else ('mid' if val >= 1 else 'low')}"
            frec = factor_bins.setdefault(tag, {"n": 0, "win": 0})
            frec["n"] += 1
            frec["win"] += int(y)

    lines = [
        f"# {args.date} Phase-A Score Sensitivity",
        "",
        "## Topic",
        "- slug: investment-research",
        f"- date: {args.date}",
        "- mode: phase-a-score-sensitivity",
        f"- windowDays: {int(args.window_days)}",
        "- source: db:scenario_gate_diagnostics + db:backtest_outcomes",
        "",
        "## Summary",
        f"- evaluatedRows: {evaluated}",
        "",
        "## Win Rate by Scenario Score Bucket",
    ]
    for k in ("85+", "75-84", "65-74", "<65"):
        rec = score_bins.get(k, {"n": 0, "win": 0})
        lines.append(f"- {k}: n={rec['n']} win={rec['win']} winRate={pct(rec['win'], rec['n']):.1f}%")

    lines.extend(["", "## Win Rate by Phase-A Factor Bin"])
    for key in sorted(factor_bins.keys()):
        rec = factor_bins[key]
        lines.append(f"- {key}: n={rec['n']} win={rec['win']} winRate={pct(rec['win'], rec['n']):.1f}%")

    lines.extend(
        [
            "",
            "## Read",
            "- high bin の勝率が継続的に低い要素は、次回の重み調整で減点対象。",
            "- low bin より high bin が有意に高い要素は、次回の重み調整で加点余地あり。",
            "- Phase B は市場/セクター地合いの方向一致を評価するため、相場転換期は過信しない。",
        ]
    )

    out.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)} rows={evaluated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
