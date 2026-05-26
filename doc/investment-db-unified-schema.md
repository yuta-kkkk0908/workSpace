# Investment DB Unified Schema

## Scope
- DB中心（可変項目はJSONカラム）
- 正本は `data/investment.db`

## Domain Split
- `raw`: 収集時の生イベント
  - `raw_events`
- `facts`: 分析・判定に使う時系列/結果
  - `facts_price_daily`
  - `signals`
  - `entry_candidates`
  - `backtest_outcomes`
  - `opening_scenarios`
  - `execution_plan`
- `dimensions`: 銘柄や補助コンテキスト
  - `instruments`
  - `credit_status_rows`
  - `sector_context_rows`
  - `market_context_rows`
  - `technical_context_rows`
  - `board_snapshots`
  - `margin_context_rows`
- `ops`: 進捗・監視・運用メタ
  - `collection_progress`
  - `collection_artifacts`
  - `ingest_log`
  - `daily_digest`
  - `observations`

## Unique Key Policy
- 価格ファクト: `facts_price_daily (date, ticker)`
- シグナル: `signals (signal_id, date)`
- エントリー候補: `entry_candidates (date, side, candidate_type, signal_id)`
- バックテスト結果: `backtest_outcomes (outcome_id, date)` + identity unique index
- 生イベント: `raw_events (source_kind, event_hash)`
- 進捗: `collection_progress (source, partition_key)`

## Compatibility Views
- `v_price_daily`: `facts_price_daily` 互換
- `v_signal_candidates`: `signals + entry_candidates` 互換
- `v_collection_status`: `collection_progress` 互換

## Promotion Rule
- 新規項目は原則 `payload_json` に入れる
- 参照頻度・集計頻度が高い項目のみ固定カラムに昇格
