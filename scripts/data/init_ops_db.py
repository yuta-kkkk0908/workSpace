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
    """
    CREATE TABLE IF NOT EXISTS improvement_candidate (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      candidate_date TEXT NOT NULL,
      source_key TEXT NOT NULL,
      title TEXT NOT NULL,
      category TEXT NOT NULL,
      source TEXT NOT NULL,
      description TEXT NOT NULL,
      impact_score INTEGER NOT NULL DEFAULT 0,
      effort_score INTEGER NOT NULL DEFAULT 0,
      priority INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'open',
      evidence_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(candidate_date, source_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_improvement_candidate_date_priority
      ON improvement_candidate(candidate_date, priority DESC, status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_improvement_candidate_category
      ON improvement_candidate(category, candidate_date)
    """,
    """
    CREATE TABLE IF NOT EXISTS improvement_audit_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      work_item_id INTEGER NOT NULL,
      proposal_id INTEGER NOT NULL,
      candidate_date TEXT NOT NULL,
      source_key TEXT NOT NULL,
      attempt_no INTEGER NOT NULL DEFAULT 0,
      stage TEXT NOT NULL,
      round_no INTEGER NOT NULL DEFAULT 0,
      event_type TEXT NOT NULL DEFAULT 'stage',
      status TEXT,
      summary TEXT,
      blocked_reason TEXT,
      input_json TEXT NOT NULL DEFAULT '{}',
      output_json TEXT NOT NULL DEFAULT '{}',
      validation_json TEXT NOT NULL DEFAULT '{}',
      review_json TEXT NOT NULL DEFAULT '{}',
      branch_name TEXT,
      commit_sha TEXT,
      pr_url TEXT,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_improvement_audit_log_work_item_stage
      ON improvement_audit_log(work_item_id, stage, round_no, id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_improvement_audit_log_created_at
      ON improvement_audit_log(created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS improvement_audit_runs (
      audit_date TEXT PRIMARY KEY,
      window_days INTEGER NOT NULL,
      model_provider TEXT NOT NULL,
      model_name TEXT NOT NULL,
      summary_json TEXT NOT NULL,
      report_text TEXT NOT NULL,
      raw_json TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS improvement_proposals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      candidate_date TEXT NOT NULL,
      source_key TEXT NOT NULL,
      repository_full_name TEXT NOT NULL,
      proposal_title TEXT NOT NULL,
      proposal_body TEXT NOT NULL,
      proposal_body_json TEXT NOT NULL,
      labels_json TEXT NOT NULL DEFAULT '[]',
      priority INTEGER NOT NULL DEFAULT 0,
      proposal_status TEXT NOT NULL DEFAULT 'draft',
      error_message TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(candidate_date, source_key, repository_full_name)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_improvement_proposals_status
      ON improvement_proposals(candidate_date, proposal_status, priority DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS improvement_work_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      proposal_id INTEGER NOT NULL,
      candidate_date TEXT NOT NULL,
      source_key TEXT NOT NULL,
      repository_full_name TEXT NOT NULL,
      work_title TEXT NOT NULL,
      work_body_json TEXT NOT NULL,
      work_plan_json TEXT NOT NULL,
      target_files_json TEXT NOT NULL DEFAULT '[]',
      execution_commands_json TEXT NOT NULL DEFAULT '[]',
      validation_commands_json TEXT NOT NULL DEFAULT '[]',
      execution_result_json TEXT NOT NULL DEFAULT '{}',
      validation_result_json TEXT NOT NULL DEFAULT '{}',
      changed_files_json TEXT NOT NULL DEFAULT '[]',
      diff_summary_json TEXT NOT NULL DEFAULT '{}',
      audit_log_ids_json TEXT NOT NULL DEFAULT '[]',
      work_status TEXT NOT NULL DEFAULT 'open',
      work_priority INTEGER NOT NULL DEFAULT 0,
      review_status TEXT NOT NULL DEFAULT 'pending',
      claimed_by TEXT,
      claimed_at TEXT,
      started_at TEXT,
      completed_at TEXT,
      branch_name TEXT,
      commit_sha TEXT,
      pr_url TEXT,
      blocked_reason TEXT,
      attempt_count INTEGER NOT NULL DEFAULT 0,
      last_attempt_at TEXT,
      error_message TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(proposal_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_improvement_work_items_status
      ON improvement_work_items(candidate_date, work_status, work_priority DESC)
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
        conn.execute("DROP TABLE IF EXISTS improvement_work_items")
        conn.execute("DROP TABLE IF EXISTS improvement_proposals")
        for ddl in SCHEMA:
            conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()
    print(f"initialized: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
