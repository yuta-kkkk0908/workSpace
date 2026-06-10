#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.alert_labels import format_decision_warning
from utils.investment_db_path import resolve_investment_db
from utils.pipeline_events import write_pipeline_event

DEFAULT_DB = resolve_investment_db()
OUT = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily diff report for decision support quality")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--warn-winrate-drop-pp", type=float, default=3.0)
    p.add_argument("--warn-dd-drop-pp", type=float, default=2.0)
    p.add_argument("--warn-accepted-drop-ratio", type=float, default=0.2)
    p.add_argument("--warn-accepted-drop-min-prev", type=int, default=3)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def _safe_pct(n: int, d: int) -> float:
    return (n / d) * 100.0 if d > 0 else 0.0


def _daily_metrics(conn: sqlite3.Connection, date_str: str, window_days: int) -> dict:
    d0 = datetime.strptime(date_str, "%Y-%m-%d").date()
    start = (d0 - timedelta(days=max(1, int(window_days)) - 1)).isoformat()

    accepted = int(
        conn.execute(
            "SELECT COUNT(*) FROM scenario_gate_diagnostics WHERE scenario_date=? AND gate_result='accepted'",
            (date_str,),
        ).fetchone()[0]
        or 0
    )

    rows = conn.execute(
        """
        SELECT sg.payload_json, bo.t5_judge, pt.t5_return_pct
        FROM scenario_gate_diagnostics sg
        LEFT JOIN backtest_outcomes bo
          ON bo.source_signal_id = sg.signal_id
         AND bo.ticker = sg.ticker
        LEFT JOIN paper_trades pt
          ON pt.entry_date = sg.scenario_date
         AND pt.ticker = sg.ticker
         AND lower(pt.side) = lower(sg.direction)
        WHERE sg.scenario_date BETWEEN ? AND ?
          AND sg.gate_result='accepted'
        """,
        (start, date_str),
    ).fetchall()

    pass_n = 0
    pass_win = 0
    rets: list[float] = []
    for raw, t5_judge, t5_ret in rows:
        try:
            payload = json.loads(raw or "{}")
        except Exception:
            payload = {}
        if str(payload.get("scenarioTier", "")).strip().lower() == "trade":
            j = str(t5_judge or "").strip().lower()
            if j not in {"", "pending", "unjudged"}:
                pass_n += 1
                if "win" in j:
                    pass_win += 1
        if t5_ret is not None:
            try:
                rets.append(float(t5_ret))
            except Exception:
                pass

    win_rate = _safe_pct(pass_win, pass_n)
    dd_approx = 0.0
    if rets:
        eq = 1.0
        peak = 1.0
        mdd = 0.0
        for r in rets:
            eq *= 1.0 + (r / 100.0)
            if eq > peak:
                peak = eq
            dd = (eq / peak) - 1.0
            if dd < mdd:
                mdd = dd
        dd_approx = mdd * 100.0
    return {
        "date": date_str,
        "acceptedCount": accepted,
        "passT5Evaluated": pass_n,
        "passT5WinRatePct": round(win_rate, 3),
        "ddApproxPct": round(dd_approx, 3),
    }


def main() -> int:
    args = parse_args()
    d_cur = args.date
    d_prev = (datetime.strptime(d_cur, "%Y-%m-%d").date() - timedelta(days=1)).isoformat()

    conn = sqlite3.connect(args.db)
    try:
        cur = _daily_metrics(conn, d_cur, int(args.window_days))
        prev = _daily_metrics(conn, d_prev, int(args.window_days))
    finally:
        conn.close()

    win_delta = round(float(cur["passT5WinRatePct"]) - float(prev["passT5WinRatePct"]), 3)
    dd_delta = round(float(cur["ddApproxPct"]) - float(prev["ddApproxPct"]), 3)
    accepted_prev = int(prev["acceptedCount"])
    accepted_cur = int(cur["acceptedCount"])
    accepted_drop_ratio = 0.0
    if accepted_prev > 0 and accepted_cur < accepted_prev:
        accepted_drop_ratio = (accepted_prev - accepted_cur) / accepted_prev

    warnings: list[str] = []
    if win_delta <= -float(args.warn_winrate_drop_pp):
        warnings.append(f"winrate_drop:{win_delta:.3f}pp")
    if dd_delta <= -float(args.warn_dd_drop_pp):
        warnings.append(f"dd_worse:{dd_delta:.3f}pp")
    if accepted_prev >= int(args.warn_accepted_drop_min_prev) and accepted_drop_ratio >= float(args.warn_accepted_drop_ratio):
        warnings.append(f"accepted_drop:{accepted_drop_ratio:.3f}")

    improved = (win_delta > 0.0) and (dd_delta >= 0.0)
    status = "warning" if warnings else "ok"

    payload = {
        "date": d_cur,
        "previousDate": d_prev,
        "windowDays": int(args.window_days),
        "thresholds": {
            "warnWinrateDropPp": float(args.warn_winrate_drop_pp),
            "warnDdDropPp": float(args.warn_dd_drop_pp),
            "warnAcceptedDropRatio": float(args.warn_accepted_drop_ratio),
            "warnAcceptedDropMinPrev": int(args.warn_accepted_drop_min_prev),
        },
        "current": cur,
        "previous": prev,
        "diff": {
            "winRateDeltaPp": win_delta,
            "ddApproxDeltaPp": dd_delta,
            "acceptedDropRatio": round(accepted_drop_ratio, 4),
            "improved": improved,
        },
        "warnings": warnings,
        "status": status,
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-decision-support-diff.json"
        out_md = OUT / f"{args.date}-decision-support-diff.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {args.date} 決定支援差分",
            "",
            f"- 比較: {d_prev} -> {d_cur}",
            f"- 参照日数: {int(args.window_days)}",
            f"- 状態: {status}",
            f"- 改善: {'yes' if improved else 'no'}",
            f"- 勝率差分(pp): {win_delta:+.3f}",
            f"- DD差分(pp): {dd_delta:+.3f}",
            f"- 採択減少率: {accepted_drop_ratio:.3f}",
            "",
            "## 警告",
        ]
        if warnings:
            for w in warnings:
                code, _, rest = w.partition(":")
                if rest:
                    lines.append(f"- {format_decision_warning(code)}: {rest}")
                else:
                    lines.append(f"- {format_decision_warning(w)}")
        else:
            lines.append("- なし")
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    write_pipeline_event(
        pipeline="investment_analysis",
        slot="inv-scenario",
        stage="report_decision_support_diff",
        status="warning" if warnings else "ok",
        event_date=args.date,
        return_code=0,
        payload=payload,
        source_path="scripts/investment/analysis/report_decision_support_diff.py",
    )
    print(f"decision_support_diff date={args.date} status={status} warnings={len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
