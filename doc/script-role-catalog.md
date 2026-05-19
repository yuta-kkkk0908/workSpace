# Script Role Catalog (PowerShell運用)

このドキュメントは「何を実行すると、何が起きるか」を運用目線で整理した一覧です。  
詳細なジョブ時刻は [scheduler-job-catalog.md](/mnt/e/workSpace/doc/scheduler-job-catalog.md) を参照。

## 1. 入口スクリプト（まず触るのはここ）

### 日次オーケストレーション（Python）
- `scripts/run_ops_scheduler.py`
  - `--slot night` : 夜バッチ一式（topic/needs/investment更新 + 夜間再評価）
  - `--slot inv-morning` : 朝の投資サイクル
  - `--slot inv-noon` : 昼の投資サイクル
  - `--slot inv-evening` : 夕方の投資サイクル
  - `--slot inv-scenario` : 朝の発注前シナリオ生成

実行例:
```powershell
py scripts\run_ops_scheduler.py --slot inv-morning --date 2026-05-14
```

### 投稿ラッパー（PowerShell）
- `scripts/ops/run_inv_morning_and_post.ps1`
- `scripts/ops/run_inv_noon_and_post.ps1`
- `scripts/ops/run_inv_evening_and_post.ps1`
- `scripts/ops/run_inv_scenario_and_post.ps1`
- `scripts/ops/run_night_and_post_generic.ps1`
- `scripts/ops/run_alert_and_post.ps1`

役割:
- `run_ops_scheduler.py` の実行
- 成果物を Discord へ投稿

## 2. Discord投稿系（PowerShell）

- `scripts/notify/post_signal_discord.ps1`
  - `prompts/market-signals-discord-message.txt` を投稿
  - 同文スキップ運用あり（ハッシュ判定）
- `scripts/notify/post_paper_stats_discord.ps1`
  - `prompts/paper-stats-discord-message.txt` を投稿
  - 同文スキップ運用あり（ハッシュ判定）
- `scripts/notify/post_scenario_discord.ps1`
  - `prompts/opening-scenarios-discord-message.txt` を投稿
- `scripts/notify/post_generic_discord.ps1`
  - `prompts/generic-topics-discord-message.txt` を投稿
- `scripts/notify/post_alert_discord.ps1`
  - `prompts/pending-daily/latest.status.txt` を投稿

## 3. 投資パイプライン中核（Python）

### 収集/整形
- `scripts/investment/signals/prepare_morning_market_signals.py`
  - 前日シグナルを朝向けに軽量引き継ぎ
- `scripts/investment/signals/reevaluate_market_signals.py`
  - 夜間テクニカル確認 + ランク再評価
- `scripts/investment/signals/generate_entry_candidates.py`
  - ロング/ショート候補抽出
- `scripts/investment/backtest/run_backtest_suite.py`
  - バックテスト一発実行（`quick` / `deep` / `deep-cache`）

### シナリオ生成
- `scripts/investment/collect/load_rakuten_board_snapshot.py`
  - 楽天RSS CSVを `*-board-snapshot.json` 化
- `scripts/investment/signals/build_opening_scenarios.py`
  - 意思決定カード（トリガー/再現性/行動設計/見送り条件）作成
- `scripts/notify/render_opening_scenarios_discord_message.py`
  - Discord投稿文を生成

### DB
- `scripts/data/init_investment_db.py`
  - `data/investment.db` 初期化/軽量マイグレーション
- `scripts/data/ingest_investment_db.py`
  - `market-signals` / `entry-candidates` / `rule-dashboard` 等をDB投入
- `scripts/data/build_today_brief_from_db.py`
  - DBから日次要約生成

### 検証（仮想トレード）
- `scripts/investment/backtest/register_paper_trades.py`
  - シナリオから引け成1ロット仮想エントリー登録
- `scripts/investment/backtest/report_paper_trades.py`
  - 仮想ポジションの進捗レポート出力

## 4. 汎用topic/needs DB系（Python）

- `scripts/data/init_topics_db.py`
- `scripts/data/ingest_topics_db.py`
- `scripts/data/build_today_topics_brief_from_db.py`
- `scripts/notify/render_generic_topics_discord_message.py`
- `scripts/data/init_needs_db.py`
- `scripts/data/ingest_needs_db.py`
- `scripts/build_needs_ai_queue.py`

## 5. 監視/補完通知系

- `scripts/check_daily_missing.py`
  - 日次欠損チェック + 補完プロンプト生成
- `scripts/check_scheduler_health.py`
  - スケジューラ実行ログ健全性チェック（ERROR検知/投稿ログ更新遅延検知）
- `scripts/check_daily_missing_toast.ps1`
  - Windows通知 + クリップボード補助
- `scripts/ops/run_alert_healthcheck.ps1`
  - 欠損チェック + scheduler-health の定期実行用
- `scripts/notify/post_alert_discord.ps1`
  - daily欠損と scheduler-health を統合して Alert Bot 通知

## 6. 典型コマンド（PowerShell）

```powershell
# 朝投資 + シグナル投稿
powershell -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\run_inv_morning_and_post.ps1

# 朝シナリオ + 投稿
powershell -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\ops\run_inv_scenario_and_post.ps1

# 夜バッチ + 汎用トピック投稿
powershell -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\ops\run_night_and_post_generic.ps1

# 仮想トレード登録（当日）
py scripts\register_paper_trades.py --date 2026-05-14 --lots 1 --max-trades 3
py scripts\report_paper_trades.py --date 2026-05-14

# バックテスト（軽量）
powershell -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\run_backtest_suite.ps1 quick 2026-05-14

# バックテスト（deep / ネット取得あり）
powershell -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\run_backtest_suite.ps1 deep 2026-05-14

# バックテスト（deep / cache-only）
powershell -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\run_backtest_suite.ps1 deep-cache 2026-05-14
```

## 7. 迷った時の見方

1. まず `run_*_and_post.ps1` を見る（入口）
2. 次に `run_ops_scheduler.py` の該当 `slot` を見る（実行順）
3. どの `prompts/*.txt` が投稿されるか確認する（成果物）
