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
from utils.investment_db_path import resolve_investment_db
from utils.pipeline_events import write_pipeline_event

DEFAULT_DB = resolve_investment_db()
OUT = ROOT / "topics" / "investment-research" / "inbox"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Report decision-support KPI from diagnostics + outcomes")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=30)
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True)
    return p.parse_args()


def _judge_state(v: str | None) -> str:
    s = str(v or "").strip().lower()
    if s in {"", "pending", "unjudged"}:
        return "pending"
    if "win" in s:
        return "win"
    if "lose" in s:
        return "lose"
    return "other"


def _init_bin() -> dict[str, int]:
    return {"n": 0, "win": 0, "lose": 0, "other": 0}


def _pct(n: int, d: int) -> float:
    return (n / d) * 100.0 if d > 0 else 0.0


def _classify_group(payload: dict) -> str | None:
    tier = str(payload.get("scenarioTier") or "").strip().lower()
    if tier == "trade":
        return "pass"
    if tier in {"watch", "paper_trade_only"}:
        return "hold"
    return None


def _parse_reject_reasons(raw: str | None) -> list[str]:
    s = str(raw or "").strip()
    if not s:
        return []
    try:
        data = json.loads(s)
    except Exception:
        return [s]
    if isinstance(data, list):
        return [str(x) for x in data if str(x or "").strip()]
    return [str(data)]


def _is_weak_reject(reasons: list[str]) -> bool:
    for r in reasons:
        x = str(r or "")
        if x.startswith("ruleHits<") or x.startswith("score<") or x.startswith("winRate<"):
            return True
        if x in {"RULE_THIN_GATE", "RULE_THIN_RANK", "RULE_THIN_QUALITY"}:
            return True
    return False


def _is_data_quality_reject(reasons: list[str]) -> bool:
    for r in reasons:
        x = str(r or "")
        if x in {"MATERIAL_NONE_TODAY", "NOON_DATA_GAP", "CREDIT_THIN"}:
            return True
        if x.startswith("sampleCount<"):
            return True
        if x.startswith("winRate_unknown"):
            return True
    return False


def _compute_kpi(rows: list[sqlite3.Row]) -> tuple[dict[str, dict[str, dict[str, int]]], int]:
    kpi: dict[str, dict[str, dict[str, int]]] = {
        "t5": {"pass": _init_bin(), "hold": _init_bin()},
        "t20": {"pass": _init_bin(), "hold": _init_bin()},
    }
    cohort: dict[str, dict[str, dict[str, int]]] = {
        "t5": {"promoted": _init_bin(), "rejected_weak": _init_bin(), "rejected_data_quality": _init_bin()},
        "t20": {"promoted": _init_bin(), "rejected_weak": _init_bin(), "rejected_data_quality": _init_bin()},
    }
    technical_t5: dict[str, dict[str, dict[str, int]]] = {"promoted": {}, "rejected_weak": {}, "rejected_data_quality": {}}
    evaluated_rows = 0
    for r in rows:
        gate = str(r["gate_result"] or "").strip().lower()
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except Exception:
            payload = {}
        s5 = _judge_state(r["t5_judge"])
        s20 = _judge_state(r["t20_judge"])
        if gate == "accepted":
            group = _classify_group(payload)
            if group:
                if s5 != "pending":
                    kpi["t5"][group]["n"] += 1
                    kpi["t5"][group][s5] += 1
                if s20 != "pending":
                    kpi["t20"][group]["n"] += 1
                    kpi["t20"][group][s20] += 1

        reject_reasons = _parse_reject_reasons(r["reject_reasons_json"])
        weak_reject = _is_weak_reject(reject_reasons)
        data_quality_reject = _is_data_quality_reject(reject_reasons)
        cohort_key = None
        if gate == "accepted":
            cohort_key = "promoted"
        elif gate == "rejected" and weak_reject:
            cohort_key = "rejected_weak"
        elif gate == "rejected" and data_quality_reject:
            cohort_key = "rejected_data_quality"
        if cohort_key:
            if s5 != "pending":
                cohort["t5"][cohort_key]["n"] += 1
                cohort["t5"][cohort_key][s5] += 1
                tag = str(payload.get("technicalTag") or "unknown").strip() or "unknown"
                bucket = technical_t5[cohort_key].setdefault(tag, _init_bin())
                bucket["n"] += 1
                bucket[s5] += 1
            if s20 != "pending":
                cohort["t20"][cohort_key]["n"] += 1
                cohort["t20"][cohort_key][s20] += 1
        if s5 != "pending" or s20 != "pending":
            evaluated_rows += 1
    return {"legacy": kpi, "cohort": cohort, "technical_t5": technical_t5}, evaluated_rows


def _load_rows(conn: sqlite3.Connection, start: str, end: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        WITH outcomes_latest AS (
          SELECT source_signal_id,ticker,MAX(date) AS max_date
          FROM backtest_outcomes
          GROUP BY source_signal_id,ticker
        )
        SELECT sg.scenario_date,sg.signal_id,sg.ticker,sg.direction,sg.gate_result,sg.payload_json,
               sg.reject_reasons_json,bo.t5_judge,bo.t20_judge
        FROM scenario_gate_diagnostics sg
        LEFT JOIN outcomes_latest ol
          ON ol.source_signal_id = sg.signal_id
         AND ol.ticker = sg.ticker
        LEFT JOIN backtest_outcomes bo
          ON bo.source_signal_id = ol.source_signal_id
         AND bo.ticker = ol.ticker
         AND bo.date = ol.max_date
        WHERE sg.scenario_date BETWEEN ? AND ?
        """,
        (start, end),
    ).fetchall()


def main() -> int:
    args = parse_args()
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    start = (d0 - timedelta(days=max(1, int(args.window_days)) - 1)).isoformat()
    end = args.date

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = _load_rows(conn, start, end)
        rows_7 = _load_rows(conn, (d0 - timedelta(days=6)).isoformat(), end)
        rows_30 = _load_rows(conn, (d0 - timedelta(days=29)).isoformat(), end)
        rows_90 = _load_rows(conn, (d0 - timedelta(days=89)).isoformat(), end)
    finally:
        conn.close()

    kpi, evaluated_rows = _compute_kpi(rows)
    kpi_7, _ = _compute_kpi(rows_7)
    kpi_30, _ = _compute_kpi(rows_30)
    kpi_90, _ = _compute_kpi(rows_90)

    payload = {
        "date": args.date,
        "window": {"start": start, "end": end, "days": int(args.window_days)},
        "evaluatedRows": evaluated_rows,
        "kpi": kpi,
        "cohortWindows": {
            "7d": kpi_7["cohort"],
            "30d": kpi_30["cohort"],
            "90d": kpi_90["cohort"],
        },
    }

    if args.write_files:
        out_json = OUT / f"{args.date}-decision-support-kpi.json"
        out_md = OUT / f"{args.date}-decision-support-kpi.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [
            f"# {args.date} 決定支援KPI",
            "",
            "## Topic",
            "- slug: investment-research",
            f"- window: {start} .. {end} ({int(args.window_days)}d)",
            "- source: db:scenario_gate_diagnostics + db:backtest_outcomes",
            f"- evaluatedRows: {evaluated_rows}",
            "",
            "## T+5",
        ]
        for g in ("pass", "hold"):
            rec = kpi["legacy"]["t5"][g]
            lines.append(
                f"- {g}: n={rec['n']} win={rec['win']} lose={rec['lose']} other={rec['other']} winRate={_pct(rec['win'], rec['n']):.1f}% failRate={_pct(rec['lose'], rec['n']):.1f}%"
            )
        lines.extend(["", "## T+20"])
        for g in ("pass", "hold"):
            rec = kpi["legacy"]["t20"][g]
            lines.append(
                f"- {g}: n={rec['n']} win={rec['win']} lose={rec['lose']} other={rec['other']} winRate={_pct(rec['win'], rec['n']):.1f}% failRate={_pct(rec['lose'], rec['n']):.1f}%"
            )
        lines.extend(["", "## コホート (T+5)"])
        for g in ("promoted", "rejected_weak", "rejected_data_quality"):
            rec = kpi["cohort"]["t5"][g]
            lines.append(
                f"- {g}: n={rec['n']} win={rec['win']} lose={rec['lose']} other={rec['other']} winRate={_pct(rec['win'], rec['n']):.1f}% failRate={_pct(rec['lose'], rec['n']):.1f}%"
            )
        lines.extend(["", "## コホート期間別 (T+5)"])
        for label, ck in (("7d", kpi_7["cohort"]), ("30d", kpi_30["cohort"]), ("90d", kpi_90["cohort"])):
            p = ck["t5"]["promoted"]
            rj = ck["t5"]["rejected_weak"]
            pwr = _pct(p["win"], p["n"])
            rwr = _pct(rj["win"], rj["n"])
            lines.append(
                f"- {label}: promoted={pwr:.1f}% (n={p['n']}) / rejected_weak={rwr:.1f}% (n={rj['n']}) / gap={rwr - pwr:+.1f}pt"
            )
        lines.extend(["", "## 技術タグ (T+5)"])
        for cohort_name in ("promoted", "rejected_weak", "rejected_data_quality"):
            lines.append(f"- {cohort_name}:")
            items = sorted(
                kpi["technical_t5"][cohort_name].items(),
                key=lambda kv: kv[1]["n"],
                reverse=True,
            )
            if not items:
                lines.append("  - none")
                continue
            for tag, rec in items[:12]:
                lines.append(
                    f"  - {tag}: n={rec['n']} win={rec['win']} lose={rec['lose']} wr={_pct(rec['win'], rec['n']):.1f}%"
                )
        out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"wrote {out_md.relative_to(ROOT)}")
        print(f"wrote {out_json.relative_to(ROOT)}")

    write_pipeline_event(
        pipeline="investment_analysis",
        slot="inv-scenario",
        stage="report_decision_support_kpi",
        status="ok",
        event_date=args.date,
        return_code=0,
        payload=payload,
        source_path="scripts/investment/analysis/report_decision_support_kpi.py",
    )
    print(f"decision_support_kpi date={args.date} evaluated={evaluated_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
