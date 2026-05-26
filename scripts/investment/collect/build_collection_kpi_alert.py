#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build KPI-centered collection alert payload")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--target-bars", type=int, default=200, choices=[200, 500])
    p.add_argument("--out", default="", help="optional JSON file output")
    return p.parse_args()


def level(value: float, warn: float, alert: float, reverse: bool = False) -> str:
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


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        jpx_rows = int(
            conn.execute("SELECT COUNT(*) FROM raw_events WHERE source_kind='jpx_daily' AND ingest_date=?", (args.date,)).fetchone()[0]
            or 0
        )
        tdnet_rows = int(
            conn.execute("SELECT COUNT(*) FROM tdnet_disclosures WHERE date=?", (args.date,)).fetchone()[0] or 0
        )
        ready, total = conn.execute(
            """
            SELECT
              SUM(CASE WHEN bars_collected>=? THEN 1 ELSE 0 END),
              COUNT(*)
            FROM collection_progress
            WHERE source='price_backfill_yahoo'
            """,
            (args.target_bars,),
        ).fetchone()
        ready = int((ready or 0))
        total = int((total or 0))
        bars_cov = (ready / total * 100.0) if total > 0 else 0.0
        jpx_cov = 100.0 if jpx_rows > 0 else 0.0
        # Proxy error rate from progress table.
        errors = int(
            conn.execute(
                "SELECT COUNT(*) FROM collection_progress WHERE status='error' AND COALESCE(last_date,'')>=?",
                (args.date,),
            ).fetchone()[0]
            or 0
        )
        denom = max(1, total)
        error_rate = errors / denom * 100.0
        payload = {
        "date": args.date,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "kpi": {
            "jpx_coverage_pct": jpx_cov,
            "jpx_coverage_level": level(jpx_cov, 70.0, 50.0, reverse=True),
            "bars_coverage_pct": bars_cov,
            "bars_coverage_level": level(bars_cov, 70.0, 50.0, reverse=True),
            "tdnet_rows": tdnet_rows,
            "error_rate_pct": error_rate,
            "error_rate_level": level(error_rate, 10.0, 20.0),
            "target_bars": args.target_bars,
            "ready_tickers": ready,
            "tracked_tickers": total,
        },
        }
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS collection_artifacts (
              artifact_key TEXT NOT NULL,
              artifact_date TEXT NOT NULL,
              artifact_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY(artifact_key, artifact_date)
            )
            """
        )
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
                f"collection_kpi_target_{args.target_bars}",
                args.date,
                "kpi_alert",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                payload["generated_at"],
            ),
        )
        conn.commit()
    finally:
        conn.close()
    if str(args.out).strip():
        out_path = Path(str(args.out))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"collection_kpi_alert date={args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
