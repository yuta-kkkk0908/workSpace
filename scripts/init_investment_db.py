#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "investment.db"

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
    CREATE TABLE IF NOT EXISTS daily_digest (
      topic TEXT NOT NULL,
      date TEXT NOT NULL,
      path TEXT NOT NULL,
      summary TEXT,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(topic, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS signals (
      signal_id TEXT NOT NULL,
      date TEXT NOT NULL,
      ticker TEXT,
      company TEXT,
      signal_type TEXT,
      signal_type_label_ja TEXT,
      expected_direction TEXT,
      expected_direction_label_ja TEXT,
      long_rank TEXT,
      short_rank TEXT,
      long_rank_label_ja TEXT,
      short_rank_label_ja TEXT,
      t1 TEXT,
      t5 TEXT,
      t20 TEXT,
      gate_status TEXT,
      gate_status_label_ja TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(signal_id, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entry_candidates (
      date TEXT NOT NULL,
      side TEXT NOT NULL,
      signal_id TEXT,
      ticker TEXT,
      company TEXT,
      rank TEXT,
      expected_direction TEXT,
      trade_use TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date, side, signal_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backtest_outcomes (
      outcome_id TEXT NOT NULL,
      date TEXT NOT NULL,
      source_signal_id TEXT,
      ticker TEXT,
      signal_date TEXT,
      disclosure_category TEXT,
      disclosure_category_label_ja TEXT,
      signal_type TEXT,
      signal_type_label_ja TEXT,
      expected_direction TEXT,
      expected_direction_label_ja TEXT,
      long_rank TEXT,
      short_rank TEXT,
      long_rank_label_ja TEXT,
      short_rank_label_ja TEXT,
      t1_judge TEXT,
      t5_judge TEXT,
      t20_judge TEXT,
      outcome_type TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(outcome_id, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rule_dashboard_rows (
      date TEXT NOT NULL,
      side TEXT NOT NULL,
      side_label_ja TEXT,
      bucket TEXT NOT NULL,
      bucket_label_ja TEXT,
      rule TEXT NOT NULL,
      appearances INTEGER,
      period TEXT,
      t1 TEXT,
      t5 TEXT,
      t20 TEXT,
      daily_use TEXT,
      daily_use_label_ja TEXT,
      status TEXT,
      status_label_ja TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date, side, bucket, rule)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rule_history_snapshots (
      rule_id TEXT NOT NULL,
      date TEXT NOT NULL,
      side TEXT,
      side_label_ja TEXT,
      bucket TEXT,
      bucket_label_ja TEXT,
      rule TEXT,
      appearances INTEGER,
      period TEXT,
      t1 TEXT,
      t5 TEXT,
      t20 TEXT,
      daily_use TEXT,
      daily_use_label_ja TEXT,
      status TEXT,
      status_label_ja TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(rule_id, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS paper_trades (
      trade_id TEXT PRIMARY KEY,
      mode TEXT NOT NULL DEFAULT 'live',
      entry_date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      company TEXT,
      side TEXT NOT NULL,
      lots INTEGER NOT NULL,
      entry_style TEXT NOT NULL,
      planned_entry_price REAL,
      status TEXT NOT NULL,
      signal_id TEXT,
      source_path TEXT NOT NULL,
      t1_return_pct REAL,
      t5_return_pct REAL,
      t20_return_pct REAL,
      t1_pnl_jpy REAL,
      t5_pnl_jpy REAL,
      t20_pnl_jpy REAL,
      t1_judge TEXT,
      t5_judge TEXT,
      t20_judge TEXT,
      updated_at TEXT NOT NULL
    )
    """,
]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Initialize SQLite DB for investment data")
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
        # Lightweight migration for existing DB files.
        migrations = [
            ("signals", "signal_type_label_ja", "TEXT"),
            ("signals", "expected_direction_label_ja", "TEXT"),
            ("signals", "long_rank_label_ja", "TEXT"),
            ("signals", "short_rank_label_ja", "TEXT"),
            ("signals", "gate_status_label_ja", "TEXT"),
            ("backtest_outcomes", "disclosure_category_label_ja", "TEXT"),
            ("backtest_outcomes", "signal_type_label_ja", "TEXT"),
            ("backtest_outcomes", "expected_direction_label_ja", "TEXT"),
            ("backtest_outcomes", "long_rank_label_ja", "TEXT"),
            ("backtest_outcomes", "short_rank_label_ja", "TEXT"),
            ("rule_dashboard_rows", "side_label_ja", "TEXT"),
            ("rule_dashboard_rows", "bucket_label_ja", "TEXT"),
            ("rule_dashboard_rows", "daily_use_label_ja", "TEXT"),
            ("rule_dashboard_rows", "status_label_ja", "TEXT"),
            ("rule_history_snapshots", "side_label_ja", "TEXT"),
            ("rule_history_snapshots", "bucket_label_ja", "TEXT"),
            ("rule_history_snapshots", "daily_use_label_ja", "TEXT"),
            ("rule_history_snapshots", "status_label_ja", "TEXT"),
            ("paper_trades", "mode", "TEXT"),
        ]
        for table, col, typ in migrations:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
            except sqlite3.OperationalError:
                # Column already exists.
                pass
        conn.commit()
    finally:
        conn.close()
    print(f"initialized: {db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
