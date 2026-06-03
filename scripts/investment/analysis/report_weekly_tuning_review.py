#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.reason_labels import format_quality_reason
from utils.investment_db_path import resolve_investment_db
from utils.pipeline_events import write_pipeline_event
DEFAULT_DB = resolve_investment_db()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Weekly tuning review for scenario quality and volume")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--window-days", type=int, default=7)
    return p.parse_args()


def count(conn: sqlite3.Connection, sql: str, params: tuple) -> int:
    return int((conn.execute(sql, params).fetchone() or [0])[0] or 0)


def main() -> int:
    args = parse_args()
    d0 = datetime.strptime(args.date, "%Y-%m-%d").date()
    start = (d0 - timedelta(days=max(1, args.window_days) - 1)).isoformat()
    end = args.date
    conn = sqlite3.connect(args.db)
    try:
        trade = count(
            conn,
            "SELECT COUNT(*) FROM opening_scenarios WHERE scenario_date BETWEEN ? AND ? AND COALESCE(scenario_tier,'trade')='trade'",
            (start, end),
        )
        watch = count(
            conn,
            "SELECT COUNT(*) FROM opening_scenarios WHERE scenario_date BETWEEN ? AND ? AND COALESCE(scenario_tier,'')='watch'",
            (start, end),
        )
        paper = count(
            conn,
            "SELECT COUNT(*) FROM opening_scenarios WHERE scenario_date BETWEEN ? AND ? AND COALESCE(scenario_tier,'')='paper_trade_only'",
            (start, end),
        )
        total = trade + watch + paper
        watch_ratio = round((watch / total) * 100.0, 3) if total > 0 else 0.0
        paper_ratio = round((paper / total) * 100.0, 3) if total > 0 else 0.0
        non_trade_ratio = round(((watch + paper) / total) * 100.0, 3) if total > 0 else 0.0

        n_small = count(
            conn,
            "SELECT COUNT(*) FROM opening_scenarios WHERE scenario_date BETWEEN ? AND ? AND COALESCE(estimated_winrate_text,'') LIKE '%n=%'",
            (start, end),
        )
        n_small_ratio = round((n_small / total) * 100.0, 3) if total > 0 else 0.0

        reject_rows = conn.execute(
            """
            SELECT reject_reasons_json FROM scenario_gate_diagnostics
            WHERE scenario_date BETWEEN ? AND ? AND gate_result='rejected'
            """,
            (start, end),
        ).fetchall()
        reason_counts: dict[str, int] = {}
        rejected = 0
        for (raw,) in reject_rows:
            rejected += 1
            try:
                arr = json.loads(raw or "[]")
            except Exception:
                arr = []
            if not arr:
                reason_counts["unknown"] = reason_counts.get("unknown", 0) + 1
                continue
            for r in arr:
                k = str(r or "unknown")
                reason_counts[k] = reason_counts.get(k, 0) + 1
        dominant_reason = ""
        dominant_ratio = 0.0
        if rejected > 0 and reason_counts:
            k, v = sorted(reason_counts.items(), key=lambda x: x[1], reverse=True)[0]
            dominant_reason = k
            dominant_ratio = round((v / rejected) * 100.0, 3)

        unknown_credit = count(
            conn,
            """
            SELECT COUNT(*)
            FROM credit_status_rows c
            JOIN (
              SELECT ticker, MAX(date) md FROM credit_status_rows GROUP BY ticker
            ) m ON m.ticker=c.ticker AND m.md=c.date
            WHERE COALESCE(c.credit_status,'unknown')='unknown'
            """,
            (),
        )
        all_credit = count(
            conn,
            """
            SELECT COUNT(*)
            FROM credit_status_rows c
            JOIN (
              SELECT ticker, MAX(date) md FROM credit_status_rows GROUP BY ticker
            ) m ON m.ticker=c.ticker AND m.md=c.date
            """,
            (),
        )
        unknown_credit_ratio = round((unknown_credit / all_credit) * 100.0, 3) if all_credit > 0 else 0.0

        # Quality warn trend from pipeline events (check_signal_quality status=alert).
        quality_warn_rows = conn.execute(
            """
            SELECT event_date, COUNT(*) AS c
            FROM pipeline_events
            WHERE event_date BETWEEN ? AND ?
              AND stage='check_signal_quality.py'
              AND status='alert'
            GROUP BY event_date
            ORDER BY event_date
            """,
            (start, end),
        ).fetchall()
        quality_warn_days = len(quality_warn_rows)
        quality_warn_total = int(sum(int(r[1] or 0) for r in quality_warn_rows))
        quality_reason_counts: dict[str, int] = {}
        quality_alert_payloads = conn.execute(
            """
            SELECT payload_json
            FROM pipeline_events
            WHERE event_date BETWEEN ? AND ?
              AND stage='check_signal_quality.py'
              AND status='alert'
            """,
            (start, end),
        ).fetchall()
        for (raw_payload,) in quality_alert_payloads:
            try:
                payload = json.loads(raw_payload or "{}")
            except Exception:
                payload = {}
            codes = payload.get("qualityReasonCodes") or []
            if not isinstance(codes, list):
                continue
            for c in codes:
                k = str(c or "").strip()
                if not k:
                    continue
                quality_reason_counts[k] = quality_reason_counts.get(k, 0) + 1
        max_warn_streak = 0
        cur_streak = 0
        prev_date = None
        for r in quality_warn_rows:
            d = datetime.strptime(str(r[0]), "%Y-%m-%d").date()
            if prev_date is not None and (d - prev_date).days == 1:
                cur_streak += 1
            else:
                cur_streak = 1
            max_warn_streak = max(max_warn_streak, cur_streak)
            prev_date = d

        recommendations: list[str] = []
        if dominant_ratio >= 50.0 and dominant_reason:
            recommendations.append(f"reject理由が偏在: {dominant_reason} ({dominant_ratio:.1f}%)。閾値/入力不足を重点点検。")
        if non_trade_ratio >= 65.0:
            recommendations.append(
                f"非trade比率が高い: {non_trade_ratio:.1f}%（watch={watch_ratio:.1f}%, paper={paper_ratio:.1f}%）。rule gate条件と母数のバランス調整を検討。"
            )
        if n_small_ratio >= 40.0:
            recommendations.append(f"低母数表示比率が高い: {n_small_ratio:.1f}%。outcomes補完幅の拡張を優先。")
        if unknown_credit_ratio >= 30.0:
            recommendations.append(f"credit unknown比率が高い: {unknown_credit_ratio:.1f}%。auto credit対象上限/優先順位を再調整。")
        if quality_warn_days >= 3:
            recommendations.append(
                f"QUALITY_WARN日が多い: days={quality_warn_days}, total={quality_warn_total}, maxStreak={max_warn_streak}。reasonCodes別に閾値/入力不足を切り分け。"
            )
        if quality_reason_counts:
            top_reason = sorted(quality_reason_counts.items(), key=lambda x: x[1], reverse=True)[0]
            recommendations.append(
                f"quality主因: {format_quality_reason(top_reason[0])} ({top_reason[1]}件)。該当原因の入力補完/閾値調整を優先。"
            )
        if not recommendations:
            recommendations.append("主要指標は許容範囲。現設定を維持し、来週も同基準で観測。")

        payload = {
            "date": args.date,
            "window_days": int(args.window_days),
            "window_start": start,
            "window_end": end,
            "kpi": {
                "trade_count": trade,
                "watch_count": watch,
                "paper_trade_only_count": paper,
                "watch_ratio_pct": watch_ratio,
                "paper_ratio_pct": paper_ratio,
                "non_trade_ratio_pct": non_trade_ratio,
                "low_sample_ratio_pct": n_small_ratio,
                "rejected_count": rejected,
                "dominant_reject_reason": dominant_reason,
                "dominant_reject_ratio_pct": dominant_ratio,
                "credit_unknown_ratio_pct": unknown_credit_ratio,
                "quality_warn_days": quality_warn_days,
                "quality_warn_total": quality_warn_total,
                "quality_warn_max_streak": max_warn_streak,
                "quality_reason_counts": quality_reason_counts,
            },
            "recommendations": recommendations,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
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
                "weekly_tuning_review",
                args.date,
                "weekly_tuning",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                payload["generated_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()

    out = ROOT / "topics" / "investment-research" / "inbox" / f"{args.date}-weekly-tuning-review.md"
    lines = [
        f"# {args.date} Weekly Tuning Review",
        "",
        f"- window: {start} .. {end} ({args.window_days}d)",
        f"- trade: {trade}",
        f"- watch: {watch}",
        f"- paper_trade_only: {paper}",
        f"- watch_ratio_pct: {watch_ratio:.3f}",
        f"- paper_ratio_pct: {paper_ratio:.3f}",
        f"- non_trade_ratio_pct: {non_trade_ratio:.3f}",
        f"- low_sample_ratio_pct: {n_small_ratio:.3f}",
        f"- rejected_count: {rejected}",
        f"- dominant_reject_reason: {dominant_reason or 'n/a'} ({dominant_ratio:.3f}%)",
        f"- credit_unknown_ratio_pct: {unknown_credit_ratio:.3f}",
        f"- quality_warn_days: {quality_warn_days}",
        f"- quality_warn_total: {quality_warn_total}",
        f"- quality_warn_max_streak: {max_warn_streak}",
        f"- quality_reason_counts: {quality_reason_counts}",
        "",
        "## Recommendations",
    ]
    lines.extend([f"- {r}" for r in recommendations])
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_pipeline_event(
        pipeline="investment_analysis",
        slot="night",
        stage="report_weekly_tuning_review",
        status="ok",
        event_date=args.date,
        return_code=0,
        payload=payload,
        source_path="scripts/investment/analysis/report_weekly_tuning_review.py",
    )
    print(f"weekly_tuning_review date={args.date} wrote={out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
