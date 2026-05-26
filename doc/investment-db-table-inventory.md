# Investment DB Table Inventory

## Objects
- tables:
  - `raw_events`
  - `facts_price_daily`
  - `signals`
  - `entry_candidates`
  - `backtest_outcomes`
  - `opening_scenarios`
  - `execution_plan`
  - `instruments`
  - `credit_status_rows`
  - `sector_context_rows`
  - `market_context_rows`
  - `technical_context_rows`
  - `board_snapshots`
  - `margin_context_rows`
  - `collection_progress`
  - `collection_artifacts`
  - `observations`
  - `daily_digest`
  - `ingest_log`
  - `rule_dashboard_rows`
  - `rule_history_snapshots`
  - `rule_check_candidates`
  - `short_readiness_rows`
  - `short_chart_reviews`
  - `short_rebound_reviews`
  - `short_conviction_rows`
  - `paper_trades`
  - `scenario_messages`
  - `scenario_reply_events`
  - `tdnet_disclosures`
  - `sector_market_context_rows`
- views:
  - `v_price_daily`
  - `v_signal_candidates`
  - `v_collection_status`

## Key Rules (summary)
- `raw_events`: `UNIQUE(source_kind, event_hash)`
- `facts_price_daily`: `PRIMARY KEY(date, ticker)`
- `signals`: `PRIMARY KEY(signal_id, date)`
- `entry_candidates`: `PRIMARY KEY(date, side, candidate_type, signal_id)`
- `backtest_outcomes`: `PRIMARY KEY(outcome_id, date)` + identity unique index
- `collection_progress`: `PRIMARY KEY(source, partition_key)`
- `collection_artifacts`: `PRIMARY KEY(artifact_key, artifact_date)`
