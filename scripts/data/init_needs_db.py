#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "needs.db"

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS ingest_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_at TEXT NOT NULL,
      kind TEXT NOT NULL,
      source_path TEXT NOT NULL,
      rows INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS need_items (
      need_id TEXT NOT NULL,
      date TEXT NOT NULL,
      topic TEXT NOT NULL,
      title TEXT,
      category TEXT,
      pain TEXT,
      request TEXT,
      existing_alternative TEXT,
      buildability TEXT,
      validation TEXT,
      source_label TEXT,
      source_url TEXT,
      confidence TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(need_id, date, source_path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS need_item_state (
      need_id TEXT NOT NULL,
      date TEXT NOT NULL,
      source_path TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'new',
      cluster_id TEXT,
      priority INTEGER NOT NULL DEFAULT 0,
      review_note TEXT,
      reviewed_at TEXT,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(need_id, date, source_path)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS need_clusters (
      cluster_id TEXT PRIMARY KEY,
      label TEXT NOT NULL,
      description TEXT,
      updated_at TEXT NOT NULL
    )
    """,
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize SQLite DB for product needs")
    p.add_argument("--db", default=str(DEFAULT_DB))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    db = Path(args.db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    try:
        for s in SCHEMA:
            conn.execute(s)
        conn.commit()
    finally:
        conn.close()
    print(f"initialized: {db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
