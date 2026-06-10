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
TASK_ERROR_LEVELS = {"ERROR", "EXCEPTION", "FATAL"}


def task_source_key(task_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task_name.lower()).strip("-")
    return f"ops.task.{slug or 'unknown'}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def root_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ingest scheduler/discord log files into ops.db")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--log-dir", default=str(LOG_DIR))
    return p.parse_args()


def ensure_task_recurrence_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_error_recurrence (
          source_key TEXT PRIMARY KEY,
          task_name TEXT NOT NULL,
          last_level TEXT NOT NULL,
          error_count INTEGER NOT NULL DEFAULT 0,
          first_ts TEXT NOT NULL,
          last_ts TEXT NOT NULL,
          last_message TEXT,
          last_source_file TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_error_recurrence_last_ts
          ON task_error_recurrence(last_ts)
        """
    )


def record_task_error_recurrence(
    conn: sqlite3.Connection,
    *,
    ts: str,
    task_name: str,
    level: str,
    message: str,
    source_file: str,
) -> None:
    source_key = task_source_key(task_name)
    ingested_at = now()
    conn.execute(
        """
        INSERT INTO task_error_recurrence(
          source_key, task_name, last_level, error_count, first_ts, last_ts,
          last_message, last_source_file, updated_at
        )
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_key) DO UPDATE SET
          task_name=excluded.task_name,
          last_level=excluded.last_level,
          error_count=task_error_recurrence.error_count + 1,
          first_ts=MIN(task_error_recurrence.first_ts, excluded.first_ts),
          last_ts=MAX(task_error_recurrence.last_ts, excluded.last_ts),
          last_message=CASE
            WHEN excluded.last_ts >= task_error_recurrence.last_ts THEN excluded.last_message
            ELSE task_error_recurrence.last_message
          END,
          last_source_file=CASE
            WHEN excluded.last_ts >= task_error_recurrence.last_ts THEN excluded.last_source_file
            ELSE task_error_recurrence.last_source_file
          END,
          updated_at=excluded.updated_at
        """,
        (
            source_key,
            task_name,
            level,
            1,
            ts,
            ts,
            message,
            source_file,
            ingested_at,
        ),
    )


def ingest_task_log(conn: sqlite3.Connection, path: Path) -> int:
    if not path.exists():
        return 0
    rows = 0
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = TASK_RE.match(raw)
        if not m:
            continue
        source_file = root_relative(path)
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO task_log_events(ts, task_name, level, message, source_file, raw_line, ingested_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                m.group("ts"),
                m.group("task"),
                m.group("level"),
                m.group("msg"),
                source_file,
                raw,
                now(),
            ),
        )
        if cur.rowcount:
            rows += 1
            level = m.group("level").upper()
            if level in TASK_ERROR_LEVELS:
                record_task_error_recurrence(
                    conn,
                    ts=m.group("ts"),
                    task_name=m.group("task"),
                    level=level,
                    message=m.group("msg"),
                    source_file=source_file,
                )
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
                root_relative(path),
                raw,
                now(),
            ),
        )
        rows += 1
    return rows


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    log_dir = Path(args.log_dir)

    conn = sqlite3.connect(db_path)
    try:
        ensure_task_recurrence_schema(conn)
        task_rows = ingest_task_log(conn, log_dir / "task-scheduler.log")
        discord_rows = 0
        for filename, channel in DISCORD_FILES.items():
            discord_rows += ingest_discord_log(conn, log_dir / filename, channel)
        conn.commit()
    finally:
        conn.close()

    print(f"ingested task_lines={task_rows} discord_lines={discord_rows} db={db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
