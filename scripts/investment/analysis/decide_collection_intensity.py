#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Decide temporary collection intensity action from recent KPIs")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=3)
    p.add_argument("--watch-ratio-high", type=float, default=70.0)
    p.add_argument("--low-sample-ratio-high", type=float, default=50.0)
    p.add_argument("--unknown-credit-high", type=float, default=40.0)
    p.add_argument("--price-missing-high", type=float, default=2.0)
    return p.parse_args()


def is_jp_business_day(d: datetime.date) -> tuple[bool, str]:
    if d.weekday() >= 5:
        return False, "weekend"
    try:
        import jpholiday  # type: ignore

        if jpholiday.is_holiday(d):
            return False, "jp_holiday"
        return True, "weekday_non_holiday"
    except Exception:
        # Fallback when holiday library is unavailable.
        return True, "weekday_fallback_no_holiday_lib"


def main() -> int:
    args = parse_args()
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    is_business_day, business_day_reason = is_jp_business_day(d0)
    start = (d0 - timedelta(days=max(1, args.window_days) - 1)).isoformat()
    end = args.date
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        kpi_rows = conn.execute(
            """
            SELECT artifact_date,payload_json
            FROM collection_artifacts
            WHERE artifact_key='signal_pipeline_kpi' AND artifact_date BETWEEN ? AND ?
            ORDER BY artifact_date
            """,
            (start, end),
        ).fetchall()
        wk_rows = conn.execute(
            """
            SELECT artifact_date,payload_json
            FROM collection_artifacts
            WHERE artifact_key='weekly_tuning_review' AND artifact_date BETWEEN ? AND ?
            ORDER BY artifact_date
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()

    if not kpi_rows or not wk_rows:
        action = "maintain"
        reasons = ["insufficient_artifacts"]
        metrics = {}
    else:
        missing_rates = []
        conversion_alert_days = 0
        for r in kpi_rows:
            p = json.loads(r["payload_json"] or "{}")
            missing_rates.append(
                float((((p.get("kpi") or {}).get("rates_pct") or {}).get("price_missing_rate_active_universe") or 0.0))
            )
            if bool((((p.get("alerts") or {}).get("conversion_drop") or {}).get("fired"))):
                conversion_alert_days += 1
        watch_ratios = []
        low_sample_ratios = []
        unknown_credit_ratios = []
        for r in wk_rows:
            p = json.loads(r["payload_json"] or "{}")
            k = p.get("kpi") or {}
            watch_ratios.append(float(k.get("watch_ratio_pct") or 0.0))
            low_sample_ratios.append(float(k.get("low_sample_ratio_pct") or 0.0))
            unknown_credit_ratios.append(float(k.get("credit_unknown_ratio_pct") or 0.0))

        avg_missing = round(sum(missing_rates) / max(1, len(missing_rates)), 3)
        avg_watch = round(sum(watch_ratios) / max(1, len(watch_ratios)), 3)
        avg_low_sample = round(sum(low_sample_ratios) / max(1, len(low_sample_ratios)), 3)
        avg_unknown_credit = round(sum(unknown_credit_ratios) / max(1, len(unknown_credit_ratios)), 3)

        reasons = []
        # Rollback priority: data quality is broken (business day only).
        if is_business_day and avg_missing >= float(args.price_missing_high):
            action = "rollback"
            reasons.append(f"price_missing_rate_high({avg_missing:.2f}%>={args.price_missing_high:.2f}%)")
        elif (not is_business_day) and avg_missing >= float(args.price_missing_high):
            action = "maintain"
            reasons.append(
                f"non_business_day_reference_only(price_missing={avg_missing:.2f}%>=threshold={args.price_missing_high:.2f}%)"
            )
        # Intensify when supply/quality bottleneck is clear and data quality acceptable.
        elif (
            conversion_alert_days >= max(1, len(kpi_rows) // 2)
            or avg_watch >= float(args.watch_ratio_high)
            or avg_low_sample >= float(args.low_sample_ratio_high)
            or avg_unknown_credit >= float(args.unknown_credit_high)
        ):
            action = "intensify"
            if conversion_alert_days >= max(1, len(kpi_rows) // 2):
                reasons.append(f"conversion_drop_alert_days={conversion_alert_days}/{len(kpi_rows)}")
            if avg_watch >= float(args.watch_ratio_high):
                reasons.append(f"watch_ratio_high({avg_watch:.2f}%>={args.watch_ratio_high:.2f}%)")
            if avg_low_sample >= float(args.low_sample_ratio_high):
                reasons.append(f"low_sample_ratio_high({avg_low_sample:.2f}%>={args.low_sample_ratio_high:.2f}%)")
            if avg_unknown_credit >= float(args.unknown_credit_high):
                reasons.append(f"unknown_credit_high({avg_unknown_credit:.2f}%>={args.unknown_credit_high:.2f}%)")
        else:
            action = "maintain"
            reasons.append("metrics_within_threshold")
        metrics = {
            "avg_price_missing_rate_pct": avg_missing,
            "conversion_drop_alert_days": conversion_alert_days,
            "window_kpi_days": len(kpi_rows),
            "avg_watch_ratio_pct": avg_watch,
            "avg_low_sample_ratio_pct": avg_low_sample,
            "avg_unknown_credit_ratio_pct": avg_unknown_credit,
        }

    payload = {
        "date": args.date,
        "window_days": int(args.window_days),
        "window_start": start,
        "window_end": end,
        "is_business_day": is_business_day,
        "business_day_reason": business_day_reason,
        "decision": action,
        "reasons": reasons,
        "metrics": metrics,
        "action_plan": {
            "maintain": {
                "collection_profile": "current",
                "note": "現行の収集強度を維持",
            },
            "intensify": {
                "collection_profile": "step2_plus",
                "note": "収集強度を追加拡張（max-pages/discover-latest/max-tickers）",
                "suggested_changes": {
                    "kabutan_discover_latest": "+5",
                    "kabutan_max_pages": "+10",
                    "credit_max_tickers": "+10",
                },
            },
            "rollback": {
                "collection_profile": "step1_or_lower",
                "note": "品質優先で直前強化を一段戻す",
                "suggested_changes": {
                    "kabutan_discover_latest": "-5",
                    "kabutan_max_pages": "-10",
                    "credit_max_tickers": "-10",
                },
            },
        }.get(action, {"collection_profile": "current", "note": "no-op"}),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }

    conn = sqlite3.connect(args.db)
    try:
        conn.execute(
            """
            INSERT INTO collection_artifacts(artifact_key,artifact_date,artifact_type,payload_json,updated_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(artifact_key,artifact_date) DO UPDATE SET
              artifact_type=excluded.artifact_type,
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (
                "collection_intensity_decision",
                args.date,
                "ops_decision",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                payload["generated_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    out = ROOT / "topics" / "investment-research" / "inbox" / f"{args.date}-collection-intensity-decision.md"
    lines = [
        f"# {args.date} Collection Intensity Decision",
        "",
        f"- window: {start} .. {end} ({args.window_days}d)",
        f"- decision: {action}",
        "## Reasons",
    ]
    lines.extend([f"- {r}" for r in reasons])
    lines.extend(["", "## Metrics"])
    for k, v in (metrics or {}).items():
        lines.append(f"- {k}: {v}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"collection_intensity_decision date={args.date} decision={action} wrote={out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
