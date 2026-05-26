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
    p = argparse.ArgumentParser(description="Build coverage-first collection queue")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--target-bars", type=int, default=200, choices=[200, 500])
    p.add_argument("--max-items", type=int, default=200)
    p.add_argument("--out", default="", help="optional JSON file output")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    try:
        # Universe from known entities.
        universe = sorted(
            {
                r[0]
                for t in ("instruments", "signals", "tdnet_disclosures", "credit_status_rows")
                for r in conn.execute(
                    f"SELECT DISTINCT ticker FROM {t} WHERE COALESCE(ticker,'')<>''"
                ).fetchall()
            }
        )
        queue = []
        for ticker in universe:
            bars = int(
                conn.execute("SELECT COUNT(*) FROM facts_price_daily WHERE ticker=?", (ticker,)).fetchone()[0]
                or 0
            )
            row = conn.execute(
                """
                SELECT status,last_date,bars_collected,target_bars
                FROM collection_progress
                WHERE source='price_backfill_yahoo' AND partition_key=?
                """,
                (ticker,),
            ).fetchone()
            status = str(row[0]) if row else "pending"
            last_date = str(row[1]) if row and row[1] else ""
            current_target = int((row[3] if row else 0) or 0)
            desired = max(args.target_bars, current_target)
            gap = max(0, desired - bars)
            if gap <= 0:
                continue
            queue.append(
                {
                    "source": "price_backfill_yahoo",
                    "ticker": ticker,
                    "priority": gap,
                    "bars_collected": bars,
                    "target_bars": desired,
                    "gap_bars": gap,
                    "status": status,
                    "last_date": last_date,
                }
            )
        queue.sort(key=lambda x: (-int(x["priority"]), str(x["ticker"])))
        queue = queue[: max(1, args.max_items)]
        payload = {
            "date": args.date,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "target_bars": args.target_bars,
            "queue_size": len(queue),
            "queue": queue,
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
        now = payload["generated_at"]
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
                f"price_backfill_target_{args.target_bars}",
                args.date,
                "coverage_plan",
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    if str(args.out).strip():
        out_path = Path(str(args.out))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"coverage_plan date={args.date} target={args.target_bars} items={len(queue)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
