#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
JST = timezone(timedelta(hours=9))
DEFAULT_DB = ROOT / "data" / "investment.db"
OUTPUT_JSON = ROOT / "topics/investment-research/rule-history.json"
OUTPUT_MD = ROOT / "topics/investment-research/rule-history.md"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Update cumulative rule history (DB-first).")
    p.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    return p.parse_args()


def rule_id(side: str, bucket: str, rule: str) -> str:
    return f"{side}::{bucket}::{rule.replace(' ', '_')}"


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        raise SystemExit(f"db not found: {args.db}")
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT side,bucket,rule,appearances,period,t1,t5,t20,daily_use,status
            FROM rule_dashboard_rows
            WHERE date=?
            """,
            (args.date,),
        ).fetchall()
        for r in rows:
            rid = rule_id(r["side"] or "", r["bucket"] or "", r["rule"] or "")
            conn.execute(
                """
                INSERT INTO rule_history_snapshots(
                  rule_id,date,side,bucket,rule,appearances,period,t1,t5,t20,daily_use,status,source_path,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                ON CONFLICT(rule_id,date) DO UPDATE SET
                  side=excluded.side,bucket=excluded.bucket,rule=excluded.rule,appearances=excluded.appearances,
                  period=excluded.period,t1=excluded.t1,t5=excluded.t5,t20=excluded.t20,daily_use=excluded.daily_use,
                  status=excluded.status,source_path=excluded.source_path,updated_at=excluded.updated_at
                """,
                (
                    rid,
                    args.date,
                    r["side"] or "",
                    r["bucket"] or "",
                    r["rule"] or "",
                    int(r["appearances"] or 0),
                    r["period"] or "",
                    r["t1"] or "",
                    r["t5"] or "",
                    r["t20"] or "",
                    r["daily_use"] or "",
                    r["status"] or "",
                    "db:rule_dashboard_rows",
                ),
            )
        conn.commit()

        all_rows = conn.execute(
            """
            SELECT rule_id,date,side,bucket,rule,appearances,t1,t5,t20,daily_use,status
            FROM rule_history_snapshots
            ORDER BY rule_id,date
            """
        ).fetchall()
    finally:
        conn.close()

    rules: dict[str, dict] = {}
    for r in all_rows:
        rid = r["rule_id"] or ""
        item = rules.setdefault(
            rid,
            {"side": r["side"] or "", "bucket": r["bucket"] or "", "rule": r["rule"] or "", "snapshots": []},
        )
        item["snapshots"].append(
            {
                "date": r["date"] or "",
                "appearances": int(r["appearances"] or 0),
                "t1": r["t1"] or "",
                "t5": r["t5"] or "",
                "t20": r["t20"] or "",
                "dailyUse": r["daily_use"] or "",
                "status": r["status"] or "",
            }
        )
    history = {"updatedAt": datetime.now(JST).replace(microsecond=0).isoformat(), "rules": rules}
    OUTPUT_JSON.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Investment Rule History", "", f"- updatedAt: {history['updatedAt']}", "", "## Latest Snapshot"]
    latest = []
    for item in rules.values():
        if item["snapshots"]:
            latest.append((item, item["snapshots"][-1]))
    for item, snap in latest[:120]:
        lines.append(
            f"- {item['side']} / {item['bucket']}: `{item['rule']}` latest={snap['date']} appearances={snap['appearances']} status={snap['status']}"
        )
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT_JSON.relative_to(ROOT)} rules={len(rules)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
