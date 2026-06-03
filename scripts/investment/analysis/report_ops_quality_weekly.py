#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.investment_db_path import resolve_investment_db

DEFAULT_DB = resolve_investment_db()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weekly integrated review: ops_post errors + quality reasons")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--window-days", type=int, default=7)
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    start = (d0 - timedelta(days=max(1, int(args.window_days)) - 1)).isoformat()
    end = args.date

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        ops_rows = conn.execute(
            """
            SELECT status,payload_json
            FROM pipeline_events
            WHERE event_date BETWEEN ? AND ?
              AND pipeline='ops_post'
            """,
            (start, end),
        ).fetchall()
        quality_rows = conn.execute(
            """
            SELECT status,payload_json
            FROM pipeline_events
            WHERE event_date BETWEEN ? AND ?
              AND stage='check_signal_quality.py'
              AND pipeline='investment_quality'
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()

    ops_status = Counter()
    ops_error_categories = Counter()
    for r in ops_rows:
        st = str(r["status"] or "unknown")
        ops_status[st] += 1
        cat = "unknown"
        try:
            p = json.loads(r["payload_json"] or "{}")
            cat = str(p.get("error_category") or "unknown")
        except Exception:
            pass
        if cat == "unknown" and st == "ok":
            cat = "ok"
        ops_error_categories[cat] += 1

    quality_status = Counter()
    quality_reasons = Counter()
    for r in quality_rows:
        st = str(r["status"] or "unknown")
        quality_status[st] += 1
        try:
            p = json.loads(r["payload_json"] or "{}")
        except Exception:
            p = {}
        codes = p.get("qualityReasonCodes") or []
        if isinstance(codes, list):
            for c in codes:
                k = str(c or "").strip()
                if k:
                    quality_reasons[k] += 1

    recommendations: list[str] = []
    if ops_error_categories.get("discord_delivery", 0) > 0:
        recommendations.append(
            f"discord_deliveryエラー {ops_error_categories['discord_delivery']}件。通知経路/再送タイミングを優先点検。"
        )
    if quality_reasons.get("CREDIT_THIN", 0) > 0:
        recommendations.append(
            f"CREDIT_THIN {quality_reasons['CREDIT_THIN']}件。credit取得対象拡張（max_tickers引き上げ）を継続。"
        )
    if quality_reasons.get("NOON_DATA_GAP", 0) > 0:
        recommendations.append(
            f"NOON_DATA_GAP {quality_reasons['NOON_DATA_GAP']}件。noon snapshot coverage改善を優先。"
        )
    if quality_reasons.get("MATERIAL_NONE_TODAY", 0) > 0:
        recommendations.append(
            f"MATERIAL_NONE_TODAY {quality_reasons['MATERIAL_NONE_TODAY']}件。一次ソース母数拡張を優先。"
        )
    if not recommendations:
        recommendations.append("ops/qualityとも大きな劣化なし。現行運用を継続。")

    payload = {
        "date": args.date,
        "window_days": int(args.window_days),
        "window_start": start,
        "window_end": end,
        "ops_post": {
            "status_counts": dict(ops_status),
            "error_category_counts": dict(ops_error_categories),
        },
        "quality": {
            "status_counts": dict(quality_status),
            "reason_counts": dict(quality_reasons),
        },
        "recommendations": recommendations,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    out_json = ROOT / "topics" / "investment-research" / "inbox" / f"{args.date}-ops-quality-weekly.json"
    out_md = ROOT / "topics" / "investment-research" / "inbox" / f"{args.date}-ops-quality-weekly.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# {args.date} Ops/Quality Weekly",
        "",
        f"- window: {start} .. {end} ({int(args.window_days)}d)",
        f"- ops_post.status_counts: {dict(ops_status)}",
        f"- ops_post.error_category_counts: {dict(ops_error_categories)}",
        f"- quality.status_counts: {dict(quality_status)}",
        f"- quality.reason_counts: {dict(quality_reasons)}",
        "",
        "## Recommendations",
    ]
    lines.extend([f"- {x}" for x in recommendations])
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"ops_quality_weekly date={args.date} wrote={out_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
