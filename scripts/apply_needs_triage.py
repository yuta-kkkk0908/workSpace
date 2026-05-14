#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "needs.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Apply needs triage result JSON into needs DB")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--input", required=True, help="json file with triage updates")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    updates = payload.get("updates", [])
    clusters = payload.get("clusters", [])

    conn = sqlite3.connect(args.db)
    updated = 0
    try:
        for c in clusters:
            cid = (c.get("cluster_id") or "").strip()
            if not cid:
                continue
            conn.execute(
                """
                INSERT INTO need_clusters(cluster_id,label,description,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                label=excluded.label,description=excluded.description,updated_at=excluded.updated_at
                """,
                (cid, c.get("label", cid), c.get("description", ""), now()),
            )

        for u in updates:
            nid = (u.get("need_id") or "").strip()
            if not nid:
                continue
            conn.execute(
                """
                UPDATE need_item_state
                SET status=?,
                    cluster_id=?,
                    priority=?,
                    review_note=?,
                    reviewed_at=?,
                    updated_at=?
                WHERE need_id=?
                """,
                (
                    u.get("status", "triaged"),
                    u.get("cluster_id", ""),
                    int(u.get("priority", 0)),
                    u.get("review_note", ""),
                    now(),
                    now(),
                    nid,
                ),
            )
            updated += conn.total_changes

        conn.commit()
    finally:
        conn.close()

    print(f"applied triage updates: {len(updates)}")
    print(f"clusters upserted: {len(clusters)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

