#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "ops.db"

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS task_log_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      task_name TEXT NOT NULL,
      level TEXT NOT NULL,
      message TEXT,
      source_file TEXT NOT NULL,
      raw_line TEXT NOT NULL,
      ingested_at TEXT NOT NULL,
      UNIQUE(ts, task_name, level, raw_line)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_task_log_events_task_ts
      ON task_log_events(task_name, ts)
    """,
    """
    CREATE TABLE IF NOT EXISTS discord_log_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      channel TEXT NOT NULL,
      level TEXT NOT NULL,
      message TEXT,
      source_file TEXT NOT NULL,
      raw_line TEXT NOT NULL,
      ingested_at TEXT NOT NULL,
      UNIQUE(ts, channel, level, raw_line)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_discord_log_events_channel_ts
      ON discord_log_events(channel, ts)
    """,
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize ops.db for scheduler/discord logs")
    p.add_argument("--db", default=str(DEFAULT_DB))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        for ddl in SCHEMA:
            conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()
    print(f"initialized: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
