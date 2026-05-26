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
        total = trade + watch
        watch_ratio = round((watch / total) * 100.0, 3) if total > 0 else 0.0

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

        recommendations: list[str] = []
        if dominant_ratio >= 50.0 and dominant_reason:
            recommendations.append(f"reject理由が偏在: {dominant_reason} ({dominant_ratio:.1f}%)。閾値/入力不足を重点点検。")
        if watch_ratio >= 65.0:
            recommendations.append(f"watch比率が高い: {watch_ratio:.1f}%。rule gate条件と母数のバランス調整を検討。")
        if n_small_ratio >= 40.0:
            recommendations.append(f"低母数表示比率が高い: {n_small_ratio:.1f}%。outcomes補完幅の拡張を優先。")
        if unknown_credit_ratio >= 30.0:
            recommendations.append(f"credit unknown比率が高い: {unknown_credit_ratio:.1f}%。auto credit対象上限/優先順位を再調整。")
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
                "watch_ratio_pct": watch_ratio,
                "low_sample_ratio_pct": n_small_ratio,
                "rejected_count": rejected,
                "dominant_reject_reason": dominant_reason,
                "dominant_reject_ratio_pct": dominant_ratio,
                "credit_unknown_ratio_pct": unknown_credit_ratio,
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
        f"- watch_ratio_pct: {watch_ratio:.3f}",
        f"- low_sample_ratio_pct: {n_small_ratio:.3f}",
        f"- rejected_count: {rejected}",
        f"- dominant_reject_reason: {dominant_reason or 'n/a'} ({dominant_ratio:.3f}%)",
        f"- credit_unknown_ratio_pct: {unknown_credit_ratio:.3f}",
        "",
        "## Recommendations",
    ]
    lines.extend([f"- {r}" for r in recommendations])
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"weekly_tuning_review date={args.date} wrote={out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
