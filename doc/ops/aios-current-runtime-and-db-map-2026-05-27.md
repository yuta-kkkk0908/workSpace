# AIOS 現行ランタイム/DBマップ（2026-05-27）

## 目的
- デグレ確認のため、現行の実スケジュール・実行フロー・DB書き込み先を1枚で確認できるようにする。

## 1. 現行スケジュール（Task Scheduler 実機値）
- `AIOS-Night`: 21:00 / `scripts/ops/run_night_and_post_generic.ps1`
- `AIOS-Inv-Morning`: 07:30 / `scripts/ops/run_inv_morning_and_post.ps1`
- `AIOS-Inv-Noon`: 12:10 / `scripts/ops/run_inv_noon_and_post.ps1`
- `AIOS-Inv-Evening`: 17:00 / `scripts/ops/run_inv_evening_and_post.ps1`
- `AIOS-Inv-Scenario-0810`: 平日 08:10 / `scripts/ops/run_inv_scenario_and_post.ps1`
- `AIOS-Alert-Healthcheck`: 21:20 / `scripts/ops/run_alert_and_post.ps1`
- `AIOS-Backtest-Weekly`: 日曜 03:30 / `scripts/ops/run_backtest_weekly.ps1`
- `AIOS-Data-Harvest`: 23:40 / `scripts/ops/run_data_harvest.ps1`
- `AIOS-Scenario-Replies-Sync-Morning`: 09:00-10:00 5分間隔
- `AIOS-Scenario-Replies-Sync-Noon`: 12:30-13:30 5分間隔
- `AIOS-Scenario-Replies-Sync-Evening`: 15:30-23:00 5分間隔
- `AIOS-Scenario-Replies-Sync-Manual`: 手動実行用
- `AIOS-Tasks-Channel-Sync`: 毎日 00:00 起点で1時間間隔（24h）

補足:
- `scripts/ops/register_tasks.ps1` の定義は `AIOS-Inv-Evening=17:00` と scenario reply sync の 3 窓構成に修正済み。

## 2. slot別の処理（scripts/run_ops_scheduler.py）

### night
- 主ソース:
  - ログ: `logs/task-scheduler.log`, `logs/discord-*.log`
  - 汎用トピック: Google News RSS (`collect_generic_daily_topics.py`)
  - 投資収集: JPX日足PDF / TDNET / Kabutan 系
- 主処理:
  - `collect_jpx_daily_pdf_prices.py`（JPX相場表PDF→`facts_price_daily`）
  - `init_*_db` + `ingest_*_db`
  - 投資 cycle（signals/candidates/re-eval/backfill/rule集計）
  - outcomes再計算バックフィル（30日毎日 / 90日週次 / 180日月次）
  - KPI系レポート生成
  - `render_generic_topics_discord_message.py --items-per-topic 3`
- post段（`do_night_and_post_generic.ps1`）:
  - `resend_pending_discord.ps1`
  - `post_generic_forum_discord.ps1`（`DISCORD_GENERIC_FORUM_CHANNEL_ID` がある場合）
  - `post_ops_kpi_discord.ps1`

### inv-morning
- 主ソース:
  - TDNET/Kabutan
- 主処理:
  - `build_market_signals_from_batches.py`
  - `generate_technical_signals.py`
  - `generate_entry_candidates.py`
  - `check_signal_quality.py`
- post段:
  - `post_signal_discord.ps1`
  - `post_signal_quality_alert.ps1`

### inv-noon
- 主ソース:
  - intraday snapshot（Yahoo 15m）
- 主処理:
  - `collect_intraday_signal_snapshots.py`
  - `reevaluate_market_signals_noon.py`
    - gate/score分離
    - `hold_noon_recheck` 運用
    - 理由コードを `signals.payload_json.noonReeval` に保存
  - technical/candidates 再生成
- post段:
  - `post_signal_discord.ps1`
  - `post_signal_quality_alert.ps1`

### inv-evening
- 主ソース:
  - TDNET/Kabutan
- 主処理:
  - outcomes補完（`--include-db-signals`）
  - technical context、signals再評価
  - paper stats / watch promotion / technical performance 集計
- post段:
  - `post_signal_discord.ps1`
  - `post_paper_stats_discord.ps1`
  - `post_signal_quality_alert.ps1`

### inv-scenario
- 主ソース:
  - credit自動収集（SBI/楽天系処理を含む）
  - signals / entry_candidates / rule系集計
- 主処理:
  - `build_opening_scenarios.py`
  - `build_execution_plan.py`
  - `fill_execution_plan_metrics.py`
  - `register_paper_trades.py --mode watch --tier all`
- post段:
  - `post_scenario_discord.ps1`

## 3. DBテーブルと追加される情報

### data/ops.db
- 定義: `scripts/data/init_ops_db.py`
- 主投入: `scripts/data/ingest_ops_logs.py`
- 主テーブル:
  - `task_log_events`: scheduler実行ログ
  - `discord_log_events`: discord投稿ログ
  - `discord_task_events`: task channel botイベント
  - `agent_memory_events`: memory系イベント

### data/topics.db
- 定義: `scripts/data/init_topics_db.py`
- 主投入: `scripts/data/ingest_topics_db.py`
- 主テーブル:
  - `topic_daily_digest`: topic日次要約
  - `topic_links`: topic日次URL
  - `ingest_log`: topics投入履歴

### data/needs.db
- 定義: `scripts/data/init_needs_db.py`
- 主投入: `scripts/data/ingest_needs_db.py`
- 主テーブル:
  - `need_items`: need本体
  - `need_item_state`: need状態
  - `need_clusters`: クラスタ
  - `ingest_log`: needs投入履歴

### data/investment.db
- 定義: `scripts/data/init_investment_db.py`
- 主投入: `scripts/data/ingest_investment_db.py` + 各分析/収集スクリプト
- 主要テーブル（運用で頻用）:
  - 収集/原本: `raw_events`, `tdnet_disclosures`, `credit_status_rows`, `facts_price_daily`, `collection_progress`
  - シグナル系: `signals`, `entry_candidates`, `opening_scenarios`, `execution_plan`
  - 成果/検証: `backtest_outcomes`, `paper_trades`, `rule_dashboard_rows`, `rule_history_snapshots`
  - 運用監視: `pipeline_events`, `collection_artifacts`, `signal_type_coverage_rows`, `market_signal_snapshots`
  - 通知連動: `scenario_messages`, `scenario_reply_events`

## 4. デグレ確認ポイント（現時点）
- Evening時刻:
  - 実タスクが `17:00` か（`AIOS-Inv-Evening`）。
  - `register_tasks.ps1` が `17:00` を維持しているか。
- Night投稿経路:
  - 汎用投稿は thread直postではなく forum経路（`post_generic_forum_discord.ps1`）。
  - `DISCORD_GENERIC_FORUM_CHANNEL_ID` が未設定だと generic投稿はskip。
- ポケカ混入:
  - `collect_generic_daily_topics.py` で `ポケポケ/ポケモンカードアプリ/Pocket` 除外済み。
- 価格ソース:
  - `fill_market_outcomes.py` が `facts_price_daily`（JPX優先）を参照し、欠損時のみ Yahoo フォールバックになっているか。
- JPX月跨ぎ:
  - `collect_jpx_daily_pdf_prices.py --date` が当月は `index.html`、過去月は `00-archives-XX.html` を辿れるか。
- 設定ドリフト:
  - `AIOS*` タスクは登録数が多く、`register_tasks.ps1` 管理対象外の旧タスクが残る。
  - 変更時は「register script」と「Task Scheduler実機値」を両方確認する。

## 5. 参照ソース
- スケジュール定義: `scripts/ops/register_tasks.ps1`
- オーケストレーション: `scripts/run_ops_scheduler.py`
- post段: `scripts/ops/do_*_and_post.ps1`
- DB定義: `scripts/data/init_*_db.py`
- DB投入: `scripts/data/ingest_*_db.py`
