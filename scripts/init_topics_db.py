#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "topics.db"

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
    CREATE TABLE IF NOT EXISTS topic_daily_digest (
      topic TEXT NOT NULL,
      date TEXT NOT NULL,
      path TEXT NOT NULL,
      summary TEXT,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(topic, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS topic_links (
      topic TEXT NOT NULL,
      date TEXT NOT NULL,
      path TEXT NOT NULL,
      url TEXT NOT NULL,
      label TEXT,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(topic, date, path, url)
    )
    """,
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize SQLite DB for non-investment topic data")
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

