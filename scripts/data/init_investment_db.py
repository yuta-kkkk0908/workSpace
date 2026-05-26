#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "investment.db"

SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS instruments (
      ticker TEXT PRIMARY KEY,
      name TEXT,
      market TEXT,
      sector TEXT,
      credit_eligible TEXT,
      source_kind TEXT NOT NULL DEFAULT 'derived',
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS facts_price_daily (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      open REAL,
      high REAL,
      low REAL,
      close REAL,
      volume INTEGER,
      source_kind TEXT NOT NULL,
      source_url TEXT,
      fetched_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date, ticker)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_facts_price_daily_ticker_date
      ON facts_price_daily(ticker, date)
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_progress (
      source TEXT NOT NULL,
      partition_key TEXT NOT NULL,
      last_date TEXT,
      status TEXT NOT NULL DEFAULT 'pending',
      bars_collected INTEGER NOT NULL DEFAULT 0,
      target_bars INTEGER NOT NULL DEFAULT 0,
      last_run_at TEXT,
      error_message TEXT,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(source, partition_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_collection_progress_source_status
      ON collection_progress(source, status, updated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS collection_artifacts (
      artifact_key TEXT NOT NULL,
      artifact_date TEXT NOT NULL,
      artifact_type TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(artifact_key, artifact_date)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_collection_artifacts_type_date
      ON collection_artifacts(artifact_type, artifact_date)
    """,
    """
    CREATE VIEW IF NOT EXISTS v_price_daily AS
    SELECT date,ticker,open,high,low,close,volume,source_kind,source_url,fetched_at,updated_at
    FROM facts_price_daily
    """,
    """
    CREATE VIEW IF NOT EXISTS v_signal_candidates AS
    SELECT
      s.date,
      s.signal_id,
      s.ticker,
      s.company,
      s.signal_type,
      s.expected_direction,
      s.long_rank,
      s.short_rank,
      s.gate_status,
      e.side,
      e.candidate_type,
      e.score
    FROM signals s
    LEFT JOIN entry_candidates e
      ON e.date=s.date AND e.signal_id=s.signal_id
    """,
    """
    CREATE VIEW IF NOT EXISTS v_collection_status AS
    SELECT source,partition_key,last_date,status,bars_collected,target_bars,last_run_at,error_message,updated_at
    FROM collection_progress
    """,
    """
    CREATE TABLE IF NOT EXISTS raw_events (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      event_hash TEXT NOT NULL,
      source_kind TEXT NOT NULL,
      source_url TEXT,
      event_time TEXT,
      ticker TEXT,
      ingest_date TEXT NOT NULL,
      fetched_at TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(source_kind, event_hash)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_raw_events_ingest_date
      ON raw_events(ingest_date)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_raw_events_ticker_date
      ON raw_events(ticker, ingest_date)
    """,
    """
    CREATE TABLE IF NOT EXISTS observations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      obs_date TEXT NOT NULL,
      obs_time TEXT,
      ticker TEXT,
      sector TEXT,
      tag TEXT,
      source_kind TEXT NOT NULL DEFAULT 'manual_observation',
      source_url TEXT,
      note TEXT NOT NULL,
      payload_json TEXT,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_observations_date_ticker
      ON observations(obs_date, ticker)
    """,
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
      url TEXT,
      source TEXT,
      session TEXT,
      material_signal_checked TEXT,
      external_context_checked TEXT,
      technical_signal_checked TEXT,
      payload_json TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(signal_id, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entry_candidates (
      date TEXT NOT NULL,
      side TEXT NOT NULL,
      candidate_type TEXT NOT NULL DEFAULT 'primary',
      signal_id TEXT,
      ticker TEXT,
      company TEXT,
      rank TEXT,
      long_rank TEXT,
      short_rank TEXT,
      expected_direction TEXT,
      trade_use TEXT,
      gate_status TEXT,
      material_signal_checked TEXT,
      external_context_checked TEXT,
      technical_signal_checked TEXT,
      score INTEGER,
      url TEXT,
      payload_json TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date, side, candidate_type, signal_id)
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
    CREATE UNIQUE INDEX IF NOT EXISTS ux_backtest_outcomes_identity
      ON backtest_outcomes(source_signal_id, signal_date, signal_type)
      WHERE COALESCE(source_signal_id,'')<>'' AND COALESCE(signal_date,'')<>'' AND COALESCE(signal_type,'')<>''
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS ux_entry_candidates_identity
      ON entry_candidates(date, side, candidate_type, signal_id)
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
      exit_price REAL,
      exit_reason TEXT,
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
    """
    CREATE TABLE IF NOT EXISTS scenario_messages (
      scenario_date TEXT NOT NULL,
      scenario_index INTEGER NOT NULL,
      channel_id TEXT NOT NULL,
      thread_id TEXT,
      anchor_message_id TEXT,
      message_id TEXT NOT NULL,
      ticker TEXT,
      company TEXT,
      direction TEXT,
      scenario_tier TEXT NOT NULL DEFAULT 'trade',
      watch_ladder TEXT,
      signal_id TEXT,
      source_path TEXT NOT NULL,
      posted_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(message_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scenario_reply_events (
      reply_message_id TEXT PRIMARY KEY,
      channel_id TEXT NOT NULL,
      parent_message_id TEXT NOT NULL,
      author_id TEXT NOT NULL,
      command TEXT NOT NULL,
      raw_content TEXT NOT NULL,
      parsed_json TEXT,
      processed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_plan (
      plan_id TEXT PRIMARY KEY,
      plan_date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      company TEXT,
      direction TEXT NOT NULL,
      entry REAL,
      tp REAL,
      sl REAL,
      rr REAL,
      ev REAL,
      rank TEXT,
      reasons TEXT,
      scenario_tier TEXT NOT NULL DEFAULT 'trade',
      status TEXT NOT NULL DEFAULT 'pending',
      signal_id TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS opening_scenarios (
      scenario_date TEXT NOT NULL,
      scenario_index INTEGER NOT NULL,
      signal_id TEXT,
      ticker TEXT NOT NULL,
      company TEXT,
      direction TEXT NOT NULL,
      scenario_tier TEXT NOT NULL DEFAULT 'trade',
      scenario_score INTEGER,
      rule_hit_count INTEGER,
      estimated_winrate_text TEXT,
      estimated_winrate_value REAL,
      entry_price REAL,
      take_profit_price REAL,
      stop_loss_price REAL,
      source_url TEXT,
      source_kind TEXT NOT NULL DEFAULT 'scenario',
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(scenario_date, scenario_index, source_kind)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scenario_gate_diagnostics (
      scenario_date TEXT NOT NULL,
      signal_id TEXT NOT NULL DEFAULT '',
      ticker TEXT NOT NULL,
      direction TEXT NOT NULL,
      candidate_source TEXT,
      scenario_tier TEXT,
      scenario_score INTEGER,
      rule_hit_count INTEGER,
      estimated_winrate_value REAL,
      gate_result TEXT NOT NULL,
      reject_reasons_json TEXT,
      gate_thresholds_json TEXT,
      payload_json TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(scenario_date, ticker, direction, gate_result, signal_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rule_check_candidates (
      date TEXT NOT NULL,
      min_count INTEGER NOT NULL,
      candidate_index INTEGER NOT NULL,
      rule_group TEXT,
      label TEXT,
      judgement TEXT,
      direction TEXT,
      row_count INTEGER,
      payload_json TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date, min_count, candidate_index)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS short_readiness_rows (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      signal_date TEXT NOT NULL,
      signal_type TEXT NOT NULL,
      company TEXT,
      category TEXT,
      short_rank TEXT,
      expected_direction TEXT,
      short_use_case TEXT,
      short_readiness TEXT,
      borrow_status TEXT,
      liquidity_bucket TEXT,
      avg_turnover_yen REAL,
      t1 TEXT,
      t5 TEXT,
      t20 TEXT,
      reasons_json TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker,signal_date,signal_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS short_chart_reviews (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      signal_date TEXT NOT NULL,
      signal_type TEXT NOT NULL,
      follow_through TEXT,
      rebound_risk TEXT,
      post_breakdown_days INTEGER,
      bearish_days_first5 INTEGER,
      payload_json TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker,signal_date,signal_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS short_rebound_reviews (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      signal_date TEXT NOT NULL,
      signal_type TEXT NOT NULL,
      exclusion_bucket TEXT,
      action_class TEXT,
      payload_json TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker,signal_date,signal_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS short_conviction_rows (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      signal_date TEXT NOT NULL,
      signal_type TEXT NOT NULL,
      conviction_bucket TEXT,
      reasons_json TEXT NOT NULL,
      payload_json TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker,signal_date,signal_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS board_snapshots (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      company TEXT,
      best_bid REAL,
      best_ask REAL,
      indicative_open REAL,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS margin_context_rows (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      reference_date TEXT,
      related_signal TEXT,
      margin_buy_balance REAL,
      margin_sell_balance REAL,
      margin_ratio REAL,
      margin_bucket TEXT,
      source TEXT,
      url TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS market_context_rows (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      signal_date TEXT NOT NULL,
      session TEXT,
      reaction_date TEXT,
      market_context TEXT,
      context_source TEXT,
      confidence TEXT,
      nikkei225_pct REAL,
      topix_pct REAL,
      sp500_prev_pct REAL,
      nasdaq_prev_pct REAL,
      usdjpy_prev_pct REAL,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker,signal_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_context_rows (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      sector_group TEXT,
      sector_profile TEXT,
      confidence TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sector_market_context_rows (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      signal_date TEXT NOT NULL,
      session TEXT,
      reaction_date TEXT,
      sector_profile TEXT,
      proxy_symbol TEXT,
      proxy_name TEXT,
      proxy_date TEXT,
      proxy_pct REAL,
      topix_proxy_symbol TEXT,
      topix_pct REAL,
      relative_to_topix_pct REAL,
      sector_market_context TEXT,
      context_source TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker,signal_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS technical_context_rows (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      signal_date TEXT NOT NULL,
      category TEXT,
      signal_type TEXT,
      expected TEXT,
      technical_status TEXT,
      technical_pattern TEXT,
      ma_trend TEXT,
      close_vs_ma25_bucket TEXT,
      rsi14_bucket TEXT,
      macd_bucket TEXT,
      bollinger_bucket TEXT,
      breakout20 TEXT,
      payload_json TEXT,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker,signal_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tdnet_disclosures (
      date TEXT NOT NULL,
      disclosed_at TEXT,
      ticker TEXT NOT NULL,
      company TEXT,
      title TEXT,
      category TEXT,
      tdnet_url TEXT,
      source_kind TEXT NOT NULL DEFAULT 'tdnet_web',
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker,title,tdnet_url)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS credit_status_rows (
      date TEXT NOT NULL,
      ticker TEXT NOT NULL,
      credit_status TEXT NOT NULL,
      buy_status TEXT,
      sell_status TEXT,
      source_kind TEXT NOT NULL,
      source_detail TEXT,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date,ticker)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS signal_type_coverage_rows (
      date TEXT NOT NULL,
      window_days INTEGER NOT NULL,
      signal_type TEXT NOT NULL,
      signal_count INTEGER NOT NULL,
      is_material INTEGER NOT NULL DEFAULT 0,
      is_shortage INTEGER NOT NULL DEFAULT 0,
      min_material_count INTEGER NOT NULL DEFAULT 0,
      source_path TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(date, window_days, signal_type)
    )
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
            ("signals", "url", "TEXT"),
            ("signals", "source", "TEXT"),
            ("signals", "session", "TEXT"),
            ("signals", "material_signal_checked", "TEXT"),
            ("signals", "external_context_checked", "TEXT"),
            ("signals", "technical_signal_checked", "TEXT"),
            ("signals", "payload_json", "TEXT"),
            ("entry_candidates", "candidate_type", "TEXT"),
            ("entry_candidates", "long_rank", "TEXT"),
            ("entry_candidates", "short_rank", "TEXT"),
            ("entry_candidates", "gate_status", "TEXT"),
            ("entry_candidates", "material_signal_checked", "TEXT"),
            ("entry_candidates", "external_context_checked", "TEXT"),
            ("entry_candidates", "technical_signal_checked", "TEXT"),
            ("entry_candidates", "score", "INTEGER"),
            ("entry_candidates", "url", "TEXT"),
            ("entry_candidates", "payload_json", "TEXT"),
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
            ("paper_trades", "exit_price", "REAL"),
            ("paper_trades", "exit_reason", "TEXT"),
            ("scenario_messages", "scenario_tier", "TEXT"),
            ("scenario_messages", "watch_ladder", "TEXT"),
            ("scenario_messages", "thread_id", "TEXT"),
            ("scenario_messages", "anchor_message_id", "TEXT"),
            ("collection_progress", "bars_collected", "INTEGER NOT NULL DEFAULT 0"),
            ("collection_progress", "target_bars", "INTEGER NOT NULL DEFAULT 0"),
            ("collection_progress", "last_run_at", "TEXT"),
            ("collection_progress", "error_message", "TEXT"),
            ("credit_status_rows", "buy_status", "TEXT"),
            ("credit_status_rows", "sell_status", "TEXT"),
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
