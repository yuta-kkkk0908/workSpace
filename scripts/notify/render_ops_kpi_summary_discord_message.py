#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()
DEFAULT_OUT = ROOT / "prompts" / "ops-kpi-summary-discord-message.txt"


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
        kpi = load_artifact(conn, "signal_pipeline_kpi", args.date)
        kpi_prev = load_latest_artifact_before(conn, "signal_pipeline_kpi", args.date)
        weekly = load_artifact(conn, "weekly_tuning_review", args.date)
        decision = load_artifact(conn, "collection_intensity_decision", args.date)
        runtime = load_night_runtime(conn, args.date)
        sample_trend_date, sample_trend = load_latest_pipeline_payload(
            conn, stage="report_samplecount_trade_trend", on_or_before=args.date
        )
    finally:
        conn.close()

    f = ((kpi.get("kpi") or {}).get("funnel") or {})
    f_prev = ((kpi_prev.get("kpi") or {}).get("funnel") or {})
    r = ((kpi.get("kpi") or {}).get("rates_pct") or {})
    wk = weekly.get("kpi") or {}
    dec = decision or {}
    sample_summary = sample_trend.get("summary") or {}
    sample_label = "n/a"
    if sample_summary:
        sample_label = "{0:.1f}%->{1:.1f}% ({2:+.1f}pt)".format(
            float(sample_summary.get("firstHalfRatio", 0.0)) * 100.0,
            float(sample_summary.get("secondHalfRatio", 0.0)) * 100.0,
            float(sample_summary.get("trendDelta", 0.0)) * 100.0,
        )
        if sample_trend_date and sample_trend_date != args.date:
            sample_label = f"{sample_label} @{sample_trend_date}"
    rate_alerts: list[str] = []
    alerts = kpi.get("alerts") or {}
    if ((alerts.get("conversion_drop") or {}).get("fired")):
        rate_alerts.append("シグナル/TDnet低下")
    if ((alerts.get("price_missing_rate") or {}).get("fired")):
        rate_alerts.append("価格欠損")
    if ((alerts.get("conversion_drop_by_type") or {}).get("fired")):
        rate_alerts.append("種別別低下")
    rate_alert_label = ", ".join(rate_alerts) if rate_alerts else "なし"
    runtime_label = str(runtime.get("status") or "missing")
    if runtime.get("duration_minutes") is not None:
        runtime_label += f" / {int(runtime['duration_minutes'])}m"

    lines = [
        f"運用夜間監視 ({args.date})",
        f"- 実行状況: {runtime_label} / 実行数={int(runtime.get('command_count', 0))} エラー数={int(runtime.get('error_count', 0))}",
        f"- 流量: 生ログ={int(f.get('raw_events', 0))} TDnet={int(f.get('tdnet_disclosures', 0))} シグナル={int(f.get('signals', 0))} 候補={int(f.get('entry_candidates', 0))} 昇格={int(f.get('opening_scenarios', 0))}",
        f"- 推移: シグナル {format_delta(f.get('signals', 0), f_prev.get('signals', 0))} / 昇格 {format_delta(f.get('opening_scenarios', 0), f_prev.get('opening_scenarios', 0))}",
        f"- 指標: シグナル/TDnet={float(r.get('signals_from_tdnet', 0.0)):.1f}% 価格欠損={float(r.get('price_missing_rate_active_universe', 0.0)):.1f}% / 警告={rate_alert_label}",
        f"- サンプル推移: {sample_label}",
        f"- 週次: 監視比率={float(wk.get('watch_ratio_pct', 0.0)):.1f}% 低サンプル={float(wk.get('low_sample_ratio_pct', 0.0)):.1f}% 却下上位={str(wk.get('dominant_reject_reason') or 'n/a')}",
        f"- 3営業日判定: {str(dec.get('decision') or 'n/a')} / 営業日={bool(dec.get('is_business_day', True))}",
        f"- 生成時刻: {datetime.now().strftime('%Y-%m-%d %H:%M JST')}",
    ]
    failures = runtime.get("failures") or []
    if failures:
        lines.append(f"- 失敗: {'; '.join(str(x) for x in failures)}")
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
