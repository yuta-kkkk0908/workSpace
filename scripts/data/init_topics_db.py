#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
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
    """
    CREATE TABLE IF NOT EXISTS topic_ai_summaries (
      topic TEXT NOT NULL,
      date TEXT NOT NULL,
      kind TEXT NOT NULL,
      provider TEXT,
      model TEXT,
      summary TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(topic, date, kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pokemon_watch_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      topic TEXT NOT NULL,
      date TEXT NOT NULL,
      source_path TEXT NOT NULL,
      file_kind TEXT NOT NULL,
      section TEXT NOT NULL,
      item_key TEXT NOT NULL,
      title TEXT NOT NULL,
      kind TEXT NOT NULL,
      status TEXT NOT NULL,
      source_name TEXT NOT NULL,
      media TEXT NOT NULL DEFAULT '',
      url TEXT NOT NULL DEFAULT '',
      product TEXT NOT NULL DEFAULT '',
      release_date TEXT NOT NULL DEFAULT '',
      start_text TEXT NOT NULL DEFAULT '',
      end_text TEXT NOT NULL DEFAULT '',
      deadline_text TEXT NOT NULL DEFAULT '',
      condition_text TEXT NOT NULL DEFAULT '',
      rank_text TEXT NOT NULL DEFAULT '',
      summary TEXT NOT NULL DEFAULT '',
      why_it_matters TEXT NOT NULL DEFAULT '',
      action_text TEXT NOT NULL DEFAULT '',
      notes TEXT NOT NULL DEFAULT '',
      raw_text TEXT NOT NULL DEFAULT '',
      collected_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(topic, date, source_path, file_kind, section, item_key, title, url)
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
