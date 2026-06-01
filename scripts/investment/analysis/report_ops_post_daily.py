#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "data" / "investment.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Daily summary for ops_post pipeline events")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT slot,stage,status,return_code,payload_json
            FROM pipeline_events
            WHERE event_date=? AND pipeline='ops_post'
            ORDER BY id
            """,
            (args.date,),
        ).fetchall()
    finally:
        conn.close()

    by_status = Counter()
    by_category = Counter()
    by_stage = Counter()
    for r in rows:
        st = str(r["status"] or "unknown")
        by_status[st] += 1
        by_stage[str(r["stage"] or "unknown")] += 1
        cat = "unknown"
        try:
            payload = json.loads(r["payload_json"] or "{}")
            cat = str(payload.get("error_category") or "unknown")
        except Exception:
            pass
        # Backfill compatibility: older ops_post rows may not have payload_json.
        if cat == "unknown" and st == "ok":
            cat = "ok"
        by_category[cat] += 1

    payload = {
        "date": args.date,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "summary": {
            "events": len(rows),
            "status_counts": dict(by_status),
            "error_category_counts": dict(by_category),
            "stage_counts": dict(by_stage),
        },
    }

    out_json = ROOT / "topics" / "investment-research" / "inbox" / f"{args.date}-ops-post-daily.json"
    out_md = ROOT / "topics" / "investment-research" / "inbox" / f"{args.date}-ops-post-daily.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# {args.date} Ops Post Daily",
        "",
        f"- events: {len(rows)}",
        f"- status_counts: {dict(by_status)}",
        f"- error_category_counts: {dict(by_category)}",
        f"- stage_counts: {dict(by_stage)}",
    ]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"ops_post_daily date={args.date} wrote={out_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
