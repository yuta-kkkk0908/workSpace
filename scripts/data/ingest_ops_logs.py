#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "ops.db"
LOG_DIR = ROOT / "logs"

TASK_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<task>[^\]]+)\]\s+\[(?P<level>[^\]]+)\]\s*(?P<msg>.*)$")
DISCORD_RE = re.compile(r"^\[(?P<ts>[^\]]+)\]\s+\[(?P<level>[^\]]+)\]\s*(?P<msg>.*)$")

DISCORD_FILES = {
    "discord-alert.log": "alert",
    "discord-generic.log": "generic",
    "discord-signal.log": "signal",
    "discord-signal-quality-alert.log": "signal_quality_alert",
}


def task_source_key(task_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task_name.lower()).strip("-")
    return f"ops.task.{slug or 'unknown'}"


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest scheduler/discord log files into ops.db")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--log-dir", default=str(LOG_DIR))
    return p.parse_args()


def ingest_task_log(conn: sqlite3.Connection, path: Path) -> int:
    if not path.exists():
        return 0
    rows = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = TASK_RE.match(raw)
        if not m:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO task_log_events(ts, task_name, level, message, source_file, raw_line, ingested_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                m.group("ts"),
                m.group("task"),
                m.group("level"),
                m.group("msg"),
                display_path(path),
                raw,
                now(),
            ),
        )
        rows += 1
    return rows


def ingest_discord_log(conn: sqlite3.Connection, path: Path, channel: str) -> int:
    if not path.exists():
        return 0
    rows = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = DISCORD_RE.match(raw)
        if not m:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO discord_log_events(ts, channel, level, message, source_file, raw_line, ingested_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                m.group("ts"),
                channel,
                m.group("level"),
                m.group("msg"),
                display_path(path),
                raw,
                now(),
            ),
        )
        rows += 1
    return rows


def ensure_recurrence_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_failure_recurrence (
          source_key TEXT PRIMARY KEY,
          task_name TEXT NOT NULL,
          error_count INTEGER NOT NULL,
          first_ts TEXT NOT NULL,
          last_ts TEXT NOT NULL,
          last_message TEXT,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_failure_recurrence_last_ts
          ON task_failure_recurrence(last_ts)
        """
    )


def refresh_failure_recurrence(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT task_name, COUNT(*) AS error_count, MIN(ts) AS first_ts, MAX(ts) AS last_ts
        FROM task_log_events
        WHERE level='ERROR'
        GROUP BY task_name
        """
    ).fetchall()
    conn.execute("DELETE FROM task_failure_recurrence")
    for task_name, error_count, first_ts, last_ts in rows:
        last = conn.execute(
            """
            SELECT message
            FROM task_log_events
            WHERE task_name=? AND level='ERROR' AND ts=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (task_name, last_ts),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO task_failure_recurrence(
              source_key, task_name, error_count, first_ts, last_ts, last_message, updated_at
            )
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                task_source_key(str(task_name)),
                task_name,
                int(error_count),
                first_ts,
                last_ts,
                last[0] if last else None,
                now(),
            ),
        )
    return len(rows)


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    log_dir = Path(args.log_dir)

    conn = sqlite3.connect(db_path)
    try:
        ensure_recurrence_table(conn)
        task_rows = ingest_task_log(conn, log_dir / "task-scheduler.log")
        discord_rows = 0
        for filename, channel in DISCORD_FILES.items():
            discord_rows += ingest_discord_log(conn, log_dir / filename, channel)
        recurrence_rows = refresh_failure_recurrence(conn)
        conn.commit()
    finally:
        conn.close()

    print(f"ingested task_lines={task_rows} discord_lines={discord_rows} recurring_failures={recurrence_rows} db={db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
