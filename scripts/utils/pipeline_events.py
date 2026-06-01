#!/usr/bin/env python3
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "investment.db"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def write_pipeline_event(
    *,
    pipeline: str,
    slot: str | None,
    stage: str | None,
    level: str = "info",
    status: str | None = None,
    command: list[str] | None = None,
    return_code: int | None = None,
    duration_ms: int | None = None,
    payload: dict[str, Any] | None = None,
    event_date: str | None = None,
    db_path: Path = DEFAULT_DB,
    source_path: str = "scripts/run_ops_scheduler.py",
) -> None:
    event_time = utc_now_iso()
    row_date = event_date or event_time[:10]
    cmd = " ".join(command) if command else None
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) if payload is not None else None
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            INSERT INTO pipeline_events(
              event_time,event_date,pipeline,slot,stage,level,status,command,return_code,duration_ms,payload_json,source_path,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_time,
                row_date,
                pipeline,
                slot,
                stage,
                level,
                status,
                cmd,
                return_code,
                duration_ms,
                payload_json,
                source_path,
                event_time,
            ),
        )
        conn.commit()
    finally:
        conn.close()

