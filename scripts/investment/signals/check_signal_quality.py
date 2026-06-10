#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROMPTS = ROOT / "prompts"
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.reason_labels import format_quality_reason
from utils.investment_db_path import resolve_investment_db
from utils.pipeline_events import write_pipeline_event

DEFAULT_DB = resolve_investment_db()

HEAD_RE = re.compile(r"^###\s+([^:]+):\s*(.+)$")
FIELD_RE = re.compile(r"^-\s+([A-Za-z0-9+_-]+):\s*(.*)$")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Quality gate for daily investment market signals")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--max-material-age-business-days", type=int, default=2)
    p.add_argument("--min-signals", type=int, default=4)
    p.add_argument("--max-side-imbalance", type=int, default=4)
    p.add_argument("--max-watch-share", type=float, default=0.7, help="alert when watch share exceeds this ratio")
    p.add_argument("--repeat-lookback-days", type=int, default=5, help="lookback window to detect repeated ticker exposure")
    p.add_argument("--repeat-min-days", type=int, default=3, help="min appeared days within lookback to flag ticker repetition")
    p.add_argument("--repeat-max-ratio", type=float, default=0.5, help="alert when repeated ticker ratio exceeds this threshold")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out-json", default=str(PROMPTS / "signal-quality-metrics.json"))
    p.add_argument("--out-alert", default=str(PROMPTS / "signal-quality-alert.txt"))
    p.add_argument("--out-diagnostics-json", default=str(PROMPTS / "signal-quality-diagnostics.json"))
    p.add_argument("--print-json", action="store_true", help="print diagnostics JSON to stdout")
    p.add_argument("--write-files", action=argparse.BooleanOptionalAction, default=True, help="write metrics/alert files (audit)")
    return p.parse_args()


def business_days_diff(start: datetime.date, end: datetime.date) -> int:
    sign = 1
    if start > end:
        start, end = end, start
        sign = -1
    d = start
    n = 0
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n * sign


def load_signals_from_db(db_path: Path, date_str: str) -> list[dict[str, str]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT signal_id,ticker,expected_direction,publishedAt as published_at
                  ,COALESCE(gate_status,'') as gate_status
                  ,COALESCE(long_rank,'') as long_rank
                  ,COALESCE(short_rank,'') as short_rank
                  ,COALESCE(material_signal_checked,'') as material_signal_checked
                  ,COALESCE(external_context_checked,'') as external_context_checked
                  ,COALESCE(technical_signal_checked,'') as technical_signal_checked
            FROM signals
            WHERE date=?
            """,
            (date_str,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(
            """
            SELECT signal_id,ticker,expected_direction,'' as published_at
                  ,COALESCE(gate_status,'') as gate_status
                  ,COALESCE(long_rank,'') as long_rank
                  ,COALESCE(short_rank,'') as short_rank
                  ,COALESCE(material_signal_checked,'') as material_signal_checked
                  ,COALESCE(external_context_checked,'') as external_context_checked
                  ,COALESCE(technical_signal_checked,'') as technical_signal_checked
            FROM signals
            WHERE date=?
            """,
            (date_str,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def main() -> int:
    args = parse_args()
    target = datetime.strptime(args.date, "%Y-%m-%d").date()
    alerts: list[str] = []
    reason_codes: list[str] = []
    metrics: dict[str, object] = {"date": args.date, "path": "db:signals"}
    rows = load_signals_from_db(args.db, args.date)
    metrics["exists"] = bool(rows)
    metrics["signalCount"] = len(rows)
    if len(rows) < args.min_signals:
        alerts.append(f"シグナル件数不足: {len(rows)} < {args.min_signals}")
        reason_codes.append("DATA_THIN")

    up = 0
    down = 0
    stale: list[str] = []
    new_count = 0
    tickers: list[str] = []
    for r in rows:
        exp = (r.get("expected_direction", "") or "").lower()
        if exp.startswith("up"):
            up += 1
        elif exp.startswith("down"):
            down += 1
        tickers.append(r.get("ticker", ""))
        pub = (r.get("published_at", "") or "")[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", pub):
            pub_d = datetime.strptime(pub, "%Y-%m-%d").date()
            age = business_days_diff(pub_d, target)
            if age == 0:
                new_count += 1
            if age > args.max_material_age_business_days:
                stale.append(f"{r.get('ticker','?')} pub={pub} age={age}bd")
    metrics["upCount"] = up
    metrics["downCount"] = down
    metrics["newMaterialCount"] = new_count
    metrics["tickers"] = tickers
    gate_pass = 0
    gate_hold = 0
    gate_hold_breakdown: dict[str, int] = {}
    long_ab = 0
    short_ab = 0
    q3_yes = 0
    for r in rows:
        gs = (r.get("gate_status", "") or "").lower()
        if gs == "pass":
            gate_pass += 1
        if gs.startswith("hold"):
            gate_hold += 1
            gate_hold_breakdown[gs] = gate_hold_breakdown.get(gs, 0) + 1
        if (r.get("long_rank", "") or "").upper().startswith(("A", "B")):
            long_ab += 1
        if (r.get("short_rank", "") or "").upper().startswith(("A", "B")):
            short_ab += 1
        if (
            (r.get("material_signal_checked", "") or "").lower() == "yes"
            and (r.get("external_context_checked", "") or "").lower() == "yes"
            and (r.get("technical_signal_checked", "") or "").lower() == "yes"
        ):
            q3_yes += 1
    metrics["gatePassCount"] = gate_pass
    metrics["gateHoldCount"] = gate_hold
    metrics["gateHoldBreakdown"] = gate_hold_breakdown
    metrics["longABCount"] = long_ab
    metrics["shortABCount"] = short_ab
    metrics["quality3YesCount"] = q3_yes
    if abs(up - down) > args.max_side_imbalance:
        alerts.append(f"方向偏り過大: up={up}, down={down}, diff={abs(up-down)}")
        reason_codes.append("SIDE_IMBALANCE")
    if stale:
        alerts.append("材料日付が古い(2営業日超): " + "; ".join(stale[:6]))
        reason_codes.append("MATERIAL_STALE")
    if rows and new_count == 0:
        alerts.append("当日材料の新規シグナルが0件")
        reason_codes.append("MATERIAL_NONE_TODAY")

    conn = sqlite3.connect(args.db)
    try:
        trade_count = conn.execute(
            "SELECT COUNT(*) FROM opening_scenarios WHERE scenario_date=? AND source_kind='scenario'",
            (args.date,),
        ).fetchone()[0]
        watch_count = conn.execute(
            "SELECT COUNT(*) FROM opening_scenarios WHERE scenario_date=? AND source_kind='rejected'",
            (args.date,),
        ).fetchone()[0]
    finally:
        conn.close()
    total = trade_count + watch_count
    watch_share = (watch_count / total) if total > 0 else 0.0
    metrics["openingScenariosPath"] = "db:opening_scenarios"
    metrics["openingScenariosDate"] = args.date
    metrics["tradeScenarioCount"] = trade_count
    metrics["becomeScenarioCount"] = trade_count
    metrics["watchScenarioCount"] = watch_count
    metrics["watchShare"] = round(watch_share, 4)
    scenario_bias_reasons: list[str] = []
    if trade_count == 0 and watch_count > 0:
        scenario_bias_reasons.append("become=0")
    if watch_share > float(args.max_watch_share):
        scenario_bias_reasons.append(f"watchShare={watch_share:.0%}>{float(args.max_watch_share):.0%}")
    if scenario_bias_reasons:
        alerts.append(
            "シナリオ構成偏り: "
            + ", ".join(scenario_bias_reasons)
            + f" (become={trade_count}, watch={watch_count})"
        )
        reason_codes.append("SCENARIO_BIAS")

    # Noon coverage diagnostics: snapshot coverage over today's signals.
    conn = sqlite3.connect(args.db)
    try:
        signal_ticker_count = conn.execute(
            "SELECT COUNT(DISTINCT ticker) FROM signals WHERE date=? AND COALESCE(ticker,'')<>''",
            (args.date,),
        ).fetchone()[0]
        noon_snapshot_ticker_count = conn.execute(
            """
            SELECT COUNT(DISTINCT ticker)
            FROM market_signal_snapshots
            WHERE date=? AND slot='inv-noon'
            """,
            (args.date,),
        ).fetchone()[0]
    except sqlite3.OperationalError:
        signal_ticker_count = 0
        noon_snapshot_ticker_count = 0
    finally:
        conn.close()
    noon_coverage = (
        (float(noon_snapshot_ticker_count) / float(signal_ticker_count))
        if signal_ticker_count > 0
        else 0.0
    )
    metrics["noonSnapshotTickerCount"] = int(noon_snapshot_ticker_count)
    metrics["noonSignalTickerCount"] = int(signal_ticker_count)
    metrics["noonCoverageRate"] = round(noon_coverage, 4)
    if signal_ticker_count > 0 and noon_coverage < 0.6:
        alerts.append(
            f"noon snapshot coverage低下: {noon_snapshot_ticker_count}/{signal_ticker_count} ({noon_coverage:.0%})"
        )
        reason_codes.append("NOON_DATA_GAP")

    # Repeated ticker detection: same names surfacing too many days in short window.
    conn = sqlite3.connect(args.db)
    try:
        rows_rep = conn.execute(
            """
            SELECT ticker, COUNT(DISTINCT date) AS appeared_days
            FROM signals
            WHERE date BETWEEN date(?, '-' || ? || ' days') AND ?
              AND COALESCE(ticker,'')<>''
            GROUP BY ticker
            """,
            (args.date, int(args.repeat_lookback_days), args.date),
        ).fetchall()
    finally:
        conn.close()
    appeared_map = {str(t): int(c or 0) for t, c in rows_rep}
    today_tickers = [str(t or "").strip() for t in tickers if str(t or "").strip()]
    repeated_today = sorted({t for t in today_tickers if appeared_map.get(t, 0) >= int(args.repeat_min_days)})
    repeat_ratio = (len(repeated_today) / len(set(today_tickers))) if today_tickers else 0.0
    metrics["repeatedTickers"] = repeated_today
    metrics["repeatedTickerCount"] = int(len(repeated_today))
    metrics["repeatedTickerRatio"] = round(repeat_ratio, 4)
    if today_tickers and repeat_ratio > float(args.repeat_max_ratio):
        alerts.append(
            f"同一銘柄の連日出現が多い: repeated={len(repeated_today)}/{len(set(today_tickers))} ({repeat_ratio:.0%})"
        )
        reason_codes.append("REPEATED_TICKER_BIAS")

    status = "ALERT" if alerts else "OK"
    metrics["status"] = status
    metrics["alerts"] = alerts
    inferred_root = "OK"
    if len(rows) < args.min_signals:
        inferred_root = "DATA_THIN"
    elif gate_pass == 0 and gate_hold > 0:
        inferred_root = "RULE_THIN_GATE"
    elif long_ab + short_ab == 0:
        inferred_root = "RULE_THIN_RANK"
    elif q3_yes == 0:
        inferred_root = "RULE_THIN_QUALITY"
    elif "NOON_DATA_GAP" in reason_codes:
        inferred_root = "NOON_DATA_GAP"
    elif unknown_ratio := (
        (sum(v for k, v in gate_hold_breakdown.items() if "credit_unknown" in k) / gate_hold)
        if gate_hold > 0
        else 0.0
    ) >= 0.6:
        inferred_root = "CREDIT_THIN"
        reason_codes.append("CREDIT_THIN")
    reason_codes_sorted = sorted(set(reason_codes))
    if inferred_root == "OK" and reason_codes_sorted:
        inferred_root = reason_codes_sorted[0]
    metrics["inferredRootCause"] = inferred_root
    metrics["qualityReasonCodes"] = reason_codes_sorted

    if args.write_files:
        out_json = Path(args.out_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diag = {
        "date": args.date,
        "status": status,
        "inferredRootCause": inferred_root,
        "signalCount": len(rows),
        "gatePassCount": gate_pass,
        "gateHoldCount": gate_hold,
        "gateHoldBreakdown": gate_hold_breakdown,
        "longABCount": long_ab,
        "shortABCount": short_ab,
        "quality3YesCount": q3_yes,
        "tradeScenarioCount": trade_count,
        "becomeScenarioCount": trade_count,
        "watchScenarioCount": watch_count,
        "watchShare": round(watch_share, 4),
        "noonSnapshotTickerCount": int(noon_snapshot_ticker_count),
        "noonSignalTickerCount": int(signal_ticker_count),
        "noonCoverageRate": round(noon_coverage, 4),
        "alerts": alerts,
        "qualityReasonCodes": reason_codes_sorted,
    }
    if args.write_files:
        out_diag = Path(args.out_diagnostics_json)
        out_diag.parent.mkdir(parents=True, exist_ok=True)
        out_diag.write_text(json.dumps(diag, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.print_json:
        print(json.dumps(diag, ensure_ascii=False))

    out_alert = Path(args.out_alert)
    if alerts:
        lines = [f"シグナル品質アラート {args.date}", "- 判定: 警告"]
        for a in alerts:
            lines.append(f"- 警告: {a}")
        lines.append(
            f"- 要約: シグナル={len(rows)} 新規={new_count} 有望={trade_count} 監視={watch_count} 監視比率={watch_share:.0%}"
        )
        lines.append(
            f"- 昼時点カバレッジ: {noon_snapshot_ticker_count}/{signal_ticker_count} ({noon_coverage:.0%})"
        )
        if gate_hold_breakdown:
            detail = ", ".join(f"{k}={v}" for k, v in sorted(gate_hold_breakdown.items()))
            lines.append(f"- 保留内訳: {detail}")
        if reason_codes_sorted:
            lines.append("- 理由コード: " + ", ".join(format_quality_reason(code) for code in reason_codes_sorted))
        if args.write_files:
            out_alert = Path(args.out_alert)
            out_alert.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if not args.print_json:
            print(f"警告: {Path(args.out_alert)}")
        write_pipeline_event(
            pipeline="investment_quality",
            slot="quality-check",
            stage="check_signal_quality.py",
            status="alert",
            event_date=args.date,
            return_code=0,
            payload=diag,
            source_path="scripts/investment/signals/check_signal_quality.py",
        )
        return 0
    else:
        if args.write_files:
            out_alert = Path(args.out_alert)
            out_alert.write_text("", encoding="utf-8")
        if not args.print_json:
            print("正常: シグナル品質")
        write_pipeline_event(
            pipeline="investment_quality",
            slot="quality-check",
            stage="check_signal_quality.py",
            status="ok",
            event_date=args.date,
            return_code=0,
            payload=diag,
            source_path="scripts/investment/signals/check_signal_quality.py",
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
