#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()
DEFAULT_OUT = ROOT / "tmp" / "prompts" / "ops-kpi-summary-discord-message.txt"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Render compact ops KPI summary for Discord")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return p.parse_args()


def load_artifact(conn: sqlite3.Connection, key: str, date_s: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT payload_json
        FROM collection_artifacts
        WHERE artifact_key=? AND artifact_date=?
        ORDER BY updated_at DESC
        LIMIT 1
        """,
        (key, date_s),
    ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(str(row[0]))
    except Exception:
        return {}


def load_latest_artifact_before(conn: sqlite3.Connection, key: str, date_s: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT payload_json
        FROM collection_artifacts
        WHERE artifact_key=? AND artifact_date<?
        ORDER BY artifact_date DESC, updated_at DESC
        LIMIT 1
        """,
        (key, date_s),
    ).fetchone()
    if not row or not row[0]:
        return {}
    try:
        return json.loads(str(row[0]))
    except Exception:
        return {}


def load_latest_collection_kpi(conn: sqlite3.Connection, date_s: str, target_bars: int) -> tuple[str | None, dict[str, Any]]:
    row = conn.execute(
        """
        SELECT artifact_date, payload_json
        FROM collection_artifacts
        WHERE artifact_key=?
          AND artifact_type='kpi_alert'
          AND artifact_date<=?
        ORDER BY artifact_date DESC, updated_at DESC
        LIMIT 1
        """,
        (f"collection_kpi_target_{target_bars}", date_s),
    ).fetchone()
    if not row:
        return None, {}
    try:
        payload = json.loads(str(row[1] or "{}"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return str(row[0] or ""), payload


def load_latest_pipeline_payload(
    conn: sqlite3.Connection, *, stage: str, on_or_before: str
) -> tuple[str | None, dict[str, Any]]:
    row = conn.execute(
        """
        SELECT event_date, payload_json
        FROM pipeline_events
        WHERE stage=? AND status='ok' AND event_date<=?
        ORDER BY event_date DESC, id DESC
        LIMIT 1
        """,
        (stage, on_or_before),
    ).fetchone()
    if not row:
        return None, {}
    try:
        payload = json.loads(str(row[1] or "{}"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return str(row[0] or ""), payload


def load_latest_inbox_payload(date_s: str, suffix: str, fallback_days: int = 3) -> tuple[str | None, dict[str, Any]]:
    d0 = datetime.strptime(date_s, "%Y-%m-%d").date()
    for i in range(0, max(0, fallback_days) + 1):
        d = (d0 - timedelta(days=i)).isoformat()
        path = ROOT / "topics" / "investment-research" / "inbox" / f"{d}-{suffix}"
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            return d, payload
    return None, {}


def _fmt_source_tag(target_date: str, source_date: str | None) -> str:
    if source_date and source_date != target_date:
        return f" @{source_date}"
    return ""


def _fmt_pct(v: Any, digits: int = 1) -> str:
    try:
        return f"{float(v or 0.0):.{digits}f}%"
    except Exception:
        return f"{0.0:.{digits}f}%"


def _level_for_ratio(value: float, warn: float, alert: float, reverse: bool = False) -> str:
    if reverse:
        if value <= alert:
            return "ALERT"
        if value <= warn:
            return "WARN"
        return "OK"
    if value >= alert:
        return "ALERT"
    if value >= warn:
        return "WARN"
    return "OK"


def _jp_level(label: str) -> str:
    return {"ALERT": "赤", "WARN": "黄", "OK": "緑"}.get(label, "不明")


def _collection_line(target_date: str, target_bars: int, source_date: str | None, payload: dict[str, Any]) -> str:
    if not payload:
        return f"- 収集 target{target_bars}: n/a"
    kpi = payload.get("kpi") or {}
    jpx = float(kpi.get("jpx_coverage_pct", 0.0))
    bars = float(kpi.get("bars_coverage_pct", 0.0))
    err = float(kpi.get("error_rate_pct", 0.0))
    label = _level_for_ratio(bars, 70.0, 50.0, reverse=True)
    return (
        f"- 収集 target{target_bars}{_fmt_source_tag(target_date, source_date)}: "
        f"jpx={_fmt_pct(jpx)} bars={_fmt_pct(bars)} error={_fmt_pct(err)} "
        f"ready={int(kpi.get('ready_tickers', 0))}/{int(kpi.get('tracked_tickers', 0))} [{label}]"
    )


def _sample_health_line(target_date: str, source_date: str | None, payload: dict[str, Any]) -> str:
    if not payload:
        return "- 分析: sample-health n/a"
    kpi = payload.get("kpi") or {}
    pending = float(kpi.get("pendingAllRatio", 0.0)) * 100.0
    effective = float(kpi.get("effectiveSampleRatio", 0.0)) * 100.0
    accepted = int(kpi.get("acceptedScenarios", 0))
    threshold = int(kpi.get("effectiveSampleThreshold", 0))
    label = _level_for_ratio(pending, 25.0, 40.0)
    return (
        f"- サンプル健全性{_fmt_source_tag(target_date, source_date)}: pending={_fmt_pct(pending)} effective={_fmt_pct(effective)} "
        f"accepted={accepted} threshold={threshold} [{label}]"
    ).replace("- サンプル健全性", "- 分析")


def _decision_diff_line(target_date: str, source_date: str | None, payload: dict[str, Any]) -> str:
    if not payload:
        return "- 分析: decision-support-diff n/a"
    current = payload.get("current") or {}
    diff = payload.get("diff") or {}
    status = str(payload.get("status") or "unknown")
    warnings = payload.get("warnings") or []
    return (
        f"- 決定支援差分{_fmt_source_tag(target_date, source_date)}: status={status} "
        f"accepted={int(current.get('acceptedCount', 0))} winΔ={float(diff.get('winRateDeltaPp', 0.0)):+.1f}pp "
        f"ddΔ={float(diff.get('ddApproxDeltaPp', 0.0)):+.1f}pp warnings={len(warnings)}"
    ).replace("- 決定支援差分", "- 分析")


def _slow_stage_lines(slow_rows: list[dict[str, Any]]) -> list[str]:
    if not slow_rows:
        return ["- 処理: 目立つ遅延ステージなし"]
    out = []
    for row in slow_rows[:3]:
        stage = str(row.get("stage") or "unknown")
        rc = int(row.get("return_code") or 0)
        dur = row.get("duration_ms")
        out.append(f"- 処理: {stage} {int(dur or 0)}ms rc={rc}")
    return out


def _processing_level(runtime: dict[str, Any], pending_files: int, freshness: list[str], slow_rows: list[dict[str, Any]]) -> str:
    if int(runtime.get("error_count", 0)) > 0:
        return "ALERT"
    if pending_files > 0:
        return "WARN"
    if slow_rows:
        return "WARN"
    if freshness and len(freshness) > 0:
        return "OK"
    return "OK"


def load_slowest_stages(conn: sqlite3.Connection, date_s: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT stage, return_code, duration_ms
        FROM pipeline_events
        WHERE pipeline='ops_scheduler'
          AND slot='night'
          AND event_date=?
          AND stage<>'slot'
        ORDER BY COALESCE(duration_ms, 0) DESC, id DESC
        LIMIT 3
        """,
        (date_s,),
    ).fetchall()
    return [
        {"stage": str(r[0] or ""), "return_code": int(r[1] or 0), "duration_ms": int(r[2] or 0)}
        for r in rows
        if r and str(r[0] or "").strip()
    ]


def load_processing_freshness() -> list[str]:
    out: list[str] = []
    for name in ("discord-signal.log", "discord-generic.log", "discord-scenario.log", "discord-paper-stats.log"):
        path = ROOT / "logs" / name
        if not path.exists():
            continue
        try:
            age = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 60.0
            out.append(f"{name}:{age:.0f}m")
        except Exception:
            continue
    out.sort(key=lambda x: float(x.split(":", 1)[1].rstrip("m")) if ":" in x else 0.0, reverse=True)
    return out


def load_night_runtime(conn: sqlite3.Connection, date_s: str) -> dict[str, Any]:
    slot_row = conn.execute(
        """
        SELECT status, payload_json
        FROM pipeline_events
        WHERE pipeline='ops_scheduler'
          AND slot='night'
          AND stage='slot'
          AND event_date=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (date_s,),
    ).fetchone()
    command_rows = conn.execute(
        """
        SELECT stage, return_code, payload_json
        FROM pipeline_events
        WHERE pipeline='ops_scheduler'
          AND slot='night'
          AND event_date=?
          AND stage<>'slot'
        ORDER BY id ASC
        """,
        (date_s,),
    ).fetchall()
    failed_rows = conn.execute(
        """
        SELECT stage, return_code, payload_json
        FROM pipeline_events
        WHERE pipeline='ops_scheduler'
          AND slot='night'
          AND event_date=?
          AND stage<>'slot'
          AND COALESCE(return_code, 0)<>0
        ORDER BY id DESC
        LIMIT 3
        """,
        (date_s,),
    ).fetchall()
    start_row = conn.execute(
        """
        SELECT event_time
        FROM pipeline_events
        WHERE pipeline='ops_scheduler'
          AND slot='night'
          AND stage='slot'
          AND event_date=?
          AND status='start'
        ORDER BY id ASC
        LIMIT 1
        """,
        (date_s,),
    ).fetchone()
    end_row = conn.execute(
        """
        SELECT event_time
        FROM pipeline_events
        WHERE pipeline='ops_scheduler'
          AND slot='night'
          AND stage='slot'
          AND event_date=?
          AND status IN ('done', 'done_with_error')
        ORDER BY id DESC
        LIMIT 1
        """,
        (date_s,),
    ).fetchone()

    final_rc = None
    status = "missing"
    if slot_row:
        status = str(slot_row[0] or "unknown")
        try:
            slot_payload = json.loads(str(slot_row[1] or "{}"))
        except Exception:
            slot_payload = {}
        if isinstance(slot_payload, dict):
            final_rc = slot_payload.get("final_rc")

    duration_minutes = None
    if start_row and end_row and start_row[0] and end_row[0]:
        try:
            start_dt = datetime.fromisoformat(str(start_row[0]).replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(str(end_row[0]).replace("Z", "+00:00"))
            duration_minutes = max(0, int((end_dt - start_dt).total_seconds() // 60))
        except ValueError:
            duration_minutes = None

    failures: list[str] = []
    for stage, rc, payload_raw in failed_rows:
        category = ""
        try:
            payload = json.loads(str(payload_raw or "{}"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            category = str(payload.get("error_category") or "")
        failures.append(f"{stage}(rc={int(rc or 0)}{', ' + category if category else ''})")

    return {
        "status": status,
        "final_rc": final_rc,
        "command_count": len(command_rows),
        "error_count": sum(1 for row in command_rows if int(row[1] or 0) != 0),
        "duration_minutes": duration_minutes,
        "failures": failures,
    }


def format_delta(current: Any, previous: Any) -> str:
    try:
        delta = int(current or 0) - int(previous or 0)
    except Exception:
        delta = 0
    return f"{delta:+d}"


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        collection_200_date, collection_200 = load_latest_collection_kpi(conn, args.date, 200)
        collection_500_date, collection_500 = load_latest_collection_kpi(conn, args.date, 500)
        signal_kpi = load_artifact(conn, "signal_pipeline_kpi", args.date)
        runtime = load_night_runtime(conn, args.date)
        slow_stages = load_slowest_stages(conn, args.date)
    finally:
        conn.close()

    collection_200_payload = collection_200
    collection_500_payload = collection_500
    signal_funnel = ((signal_kpi.get("kpi") or {}).get("funnel") or {})
    signal_rates = ((signal_kpi.get("kpi") or {}).get("rates_pct") or {})
    signal_alerts = signal_kpi.get("alerts") or {}
    signal_alert_bits: list[str] = []
    if (signal_alerts.get("conversion_drop") or {}).get("fired"):
        signal_alert_bits.append("conversion_drop")
    if (signal_alerts.get("price_missing_rate") or {}).get("fired"):
        signal_alert_bits.append("price_missing")
    if (signal_alerts.get("conversion_drop_by_type") or {}).get("fired"):
        signal_alert_bits.append("type_drop")
    signal_alert_label = ", ".join(signal_alert_bits) if signal_alert_bits else "none"

    sample_health_date, sample_health = load_latest_inbox_payload(args.date, "sample-health-kpi.json", fallback_days=7)
    diff_date, decision_diff = load_latest_inbox_payload(args.date, "decision-support-diff.json", fallback_days=7)
    pending_path = ROOT / "tmp" / "prompts" / "pending"
    pending_files = len(list(pending_path.glob("*-discord-pending-*.txt"))) if pending_path.exists() else 0
    freshness = load_processing_freshness()
    runtime_label = str(runtime.get("status") or "missing")
    if runtime.get("duration_minutes") is not None:
        runtime_label += f" / {int(runtime['duration_minutes'])}m"

    collection_200_level = "OK"
    if collection_200_payload:
        collection_200_level = str((collection_200_payload.get("kpi") or {}).get("bars_coverage_level") or "OK")
    collection_500_level = "OK"
    if collection_500_payload:
        collection_500_level = str((collection_500_payload.get("kpi") or {}).get("bars_coverage_level") or "OK")
    analysis_level = "OK"
    if sample_health:
        analysis_level = _level_for_ratio(float((sample_health.get("kpi") or {}).get("pendingAllRatio", 0.0)) * 100.0, 25.0, 40.0)
    if decision_diff and str(decision_diff.get("status") or "").lower() == "warning":
        analysis_level = "ALERT" if analysis_level == "ALERT" else "WARN"
    processing_level = _processing_level(runtime, pending_files, freshness, slow_stages)

    lines = [
        f"夜間ボトルネック観測 ({args.date})",
        f"- 総合: 収集={_jp_level(collection_200_level if collection_200_level != 'OK' else collection_500_level)} 分析={_jp_level(analysis_level)} 処理={_jp_level(processing_level)}",
        f"- 実行状況: {runtime_label} / 実行数={int(runtime.get('command_count', 0))} エラー数={int(runtime.get('error_count', 0))}",
        "",
        "## 収集",
        f"- 収集: raw={int(signal_funnel.get('raw_events', 0))} TDnet={int(signal_funnel.get('tdnet_disclosures', 0))} signals={int(signal_funnel.get('signals', 0))} candidates={int(signal_funnel.get('entry_candidates', 0))} scenarios={int(signal_funnel.get('opening_scenarios', 0))} / sig/tdnet={float(signal_rates.get('signals_from_tdnet', 0.0)):.1f}% 価格欠損={float(signal_rates.get('price_missing_rate_active_universe', 0.0)):.1f}% 警告={signal_alert_label}",
        _collection_line(args.date, 200, collection_200_date, collection_200_payload),
        _collection_line(args.date, 500, collection_500_date, collection_500_payload),
        "",
        "## 分析",
        _sample_health_line(args.date, sample_health_date, sample_health) if sample_health else "- 分析: sample-health 未生成",
        _decision_diff_line(args.date, diff_date, decision_diff) if decision_diff else "- 分析: decision-support-diff 未生成",
        "",
        "## 処理",
        f"- 処理: pending_queue={pending_files} files / freshness={', '.join(freshness[:4]) if freshness else 'n/a'}",
    ]
    if slow_stages:
        lines.extend(_slow_stage_lines(slow_stages))
    failures = runtime.get("failures") or []
    if failures:
        lines.append(f"- 失敗: {'; '.join(str(x) for x in failures)}")
    lines.append(f"- 生成時刻: {datetime.now().strftime('%Y-%m-%d %H:%M JST')}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        out_label = args.out.relative_to(ROOT)
    except ValueError:
        out_label = args.out
    print(f"wrote {out_label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
