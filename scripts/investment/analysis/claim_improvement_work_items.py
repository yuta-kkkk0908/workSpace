#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from utils.platform_core_bootstrap import ensure_platform_core_importable

ensure_platform_core_importable()

DEFAULT_OPS_DB = ROOT / "data" / "ops.db"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Claim open improvement work items")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--db", type=Path, default=DEFAULT_OPS_DB)
    p.add_argument("--limit", type=int, default=3)
    p.add_argument("--claimant", default="", help="Override claimant label")
    return p.parse_args()


def claimant_name(explicit: str) -> str:
    if explicit.strip():
        return explicit.strip()
    return (
        os.environ.get("CODEX_AGENT", "").strip()
        or os.environ.get("USER", "").strip()
        or os.environ.get("USERNAME", "").strip()
        or "codex"
    )


def load_open_items(conn: sqlite3.Connection, date_s: str, limit: int) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT *
        FROM improvement_work_items
        WHERE candidate_date <= ?
          AND work_status = 'open'
        ORDER BY work_priority DESC, candidate_date ASC, id ASC
        LIMIT ?
        """,
        (date_s, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def claim_item(conn: sqlite3.Connection, item_id: int, claimant: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        UPDATE improvement_work_items
        SET work_status='doing',
            claimed_by=?,
            claimed_at=COALESCE(claimed_at, ?),
            started_at=COALESCE(started_at, ?),
            updated_at=?
        WHERE id=? AND work_status='open'
        """,
        (claimant, now, now, now, item_id),
    )


def main() -> int:
    args = parse_args()
    claimant = claimant_name(args.claimant)
    conn = sqlite3.connect(args.db)
    try:
        items = load_open_items(conn, args.date, args.limit)
        if not items:
            print("skip: no open work items")
            return 0

        claimed = 0
        for item in items:
            claim_item(conn, int(item["id"]), claimant)
            claimed += 1

        conn.commit()
    finally:
        conn.close()

    print(f"claimed: improvement_work_items {claimed} rows claimant={claimant}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
