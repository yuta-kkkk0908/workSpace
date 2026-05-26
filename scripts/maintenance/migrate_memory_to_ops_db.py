#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INV_DB = ROOT / "data" / "investment.db"
OPS_DB = ROOT / "data" / "ops.db"


def ensure_ops_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
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
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agent_memory_topic_date
          ON agent_memory_events(topic, memory_date, updated_at)
        """
    )


def main() -> int:
    if not INV_DB.exists():
        print("investment.db not found; skip")
        return 0
    OPS_DB.parent.mkdir(parents=True, exist_ok=True)
    inv = sqlite3.connect(INV_DB)
    ops = sqlite3.connect(OPS_DB)
    moved = 0
    try:
        ensure_ops_schema(ops)
        try:
            rows = inv.execute(
                """
                SELECT memory_date,topic,memory_type,content,status,source_channel_id,source_message_id,source_author_id,payload_json,updated_at
                FROM agent_memory_events
                """
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for r in rows:
            exists = ops.execute(
                """
                SELECT 1 FROM agent_memory_events
                WHERE memory_date=? AND topic=? AND memory_type=? AND content=? AND COALESCE(source_message_id,'')=COALESCE(?, '')
                LIMIT 1
                """,
                (r[0], r[1], r[2], r[3], r[6]),
            ).fetchone()
            if exists:
                continue
            ops.execute(
                """
                INSERT INTO agent_memory_events(
                  memory_date,topic,memory_type,content,status,source_channel_id,source_message_id,source_author_id,payload_json,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                r,
            )
            moved += 1
        ops.commit()
    finally:
        inv.close()
        ops.close()
    print(f"migrated_memory_rows={moved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
