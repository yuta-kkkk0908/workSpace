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
                str(path.relative_to(ROOT)),
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
                str(path.relative_to(ROOT)),
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
