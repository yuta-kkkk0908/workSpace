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
    """
    CREATE TABLE IF NOT EXISTS discord_task_events (
      message_id TEXT PRIMARY KEY,
      channel_id TEXT NOT NULL,
      author_id TEXT NOT NULL,
      raw_content TEXT NOT NULL,
      command_name TEXT,
      command_args_json TEXT,
      status TEXT NOT NULL,
      result_json TEXT,
      processed_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_discord_task_events_processed_at
      ON discord_task_events(processed_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_memory_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      memory_date TEXT NOT NULL,
      topic TEXT NOT NULL,
      memory_type TEXT NOT NULL,
      content TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active',
      source_channel_id TEXT,
      source_message_id TEXT,
      source_author_id TEXT,
      payload_json TEXT,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_memory_topic_date
      ON agent_memory_events(topic, memory_date, updated_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_memory_source_message
      ON agent_memory_events(source_channel_id, source_message_id)
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
