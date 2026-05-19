# Scheduler Job Catalog

このドキュメントは、Windows Task Scheduler に登録した定期実行ジョブの台帳です。  
今後ジョブを追加・変更したら、このファイルに追記してください。

## 実行ログ

- 共通ログ: `logs/task-scheduler.log`
- 形式: `[timestamp] [TaskName] [START|OK|ERROR|EXCEPTION|END] message`
- まずここを見れば「実行したか / 成功したか / 何時に終わったか」が判定できる。

## 更新ルール

- 追加時: `## Job` を1ブロック追加する
- 変更時: 対象Jobの「目的」「実行コマンド」「処理内容」を更新する
- 廃止時: 削除せず `status: retired` にして履歴を残す

---

## Job: AIOS-Night

- status: active
- schedule: 毎日 21:00
- entrypoint: `scripts/run_ops_scheduler.py --slot night --date YYYY-MM-DD`
- 目的:
  - 全topicの夜間更新をまとめて実行する
  - 翌日の `今日の情報` 用DBを更新する
- 処理内容:
  - 日次取り逃しチェック  
    - `scripts/check_daily_missing.py --date today --days 7`
  - 汎用トピック自動収集（RSSベース）
    - `scripts/investment/collect/collect_generic_daily_topics.py --date YYYY-MM-DD --overwrite`
  - 非投資topic DB更新  
    - `scripts/data/init_topics_db.py`  
    - `scripts/data/ingest_topics_db.py --date YYYY-MM-DD`  
    - `scripts/data/build_today_topics_brief_from_db.py --date YYYY-MM-DD`
    - `scripts/notify/render_generic_topics_discord_message.py --date YYYY-MM-DD`
  - ニーズDB更新  
    - `scripts/data/init_needs_db.py`  
    - `scripts/data/ingest_needs_db.py --date YYYY-MM-DD`  
    - `scripts/build_needs_ai_queue.py --limit 20`
  - 投資DB更新  
    - `scripts/data/init_investment_db.py`  
    - `scripts/data/ingest_investment_db.py --date YYYY-MM-DD`  
    - `scripts/data/build_today_brief_from_db.py --date YYYY-MM-DD`
  - 投資サイクル（夜）  
    - `scripts/investment/signals/check_investment_signal_missing.py --date YYYY-MM-DD`  
    - `scripts/investment/signals/generate_entry_candidates.py --date YYYY-MM-DD`  
    - `scripts/data/init_investment_db.py`  
    - `scripts/data/ingest_investment_db.py --date YYYY-MM-DD`  
    - `scripts/data/build_today_brief_from_db.py --date YYYY-MM-DD`

---

## Job: AIOS-Inv-Morning

- status: active
- schedule: 毎日 07:30
- entrypoint: `scripts/run_ops_scheduler.py --slot inv-morning --date YYYY-MM-DD`
- 目的:
  - 朝の投資監視データを更新する
- 処理内容:
  - 投資サイクル実行
    - `scripts/investment/signals/prepare_morning_market_signals.py --date YYYY-MM-DD --fallback-days 3`
    - `scripts/investment/signals/check_investment_signal_missing.py --date YYYY-MM-DD`
    - `scripts/investment/signals/generate_entry_candidates.py --date YYYY-MM-DD --fallback-days 3`
    - `scripts/data/init_investment_db.py`
    - `scripts/data/ingest_investment_db.py --date YYYY-MM-DD`
    - `scripts/data/build_today_brief_from_db.py --date YYYY-MM-DD`
    - `scripts/notify/render_market_signals_discord_message.py --date YYYY-MM-DD --fallback-days 3`

---

## Job: AIOS-Inv-Noon

- status: active
- schedule: 毎日 12:10
- entrypoint: `scripts/run_ops_scheduler.py --slot inv-noon --date YYYY-MM-DD`
- 目的:
  - 昼時点の投資監視データを再更新する
- 処理内容:
  - 投資サイクル実行（Morningと同じ）

---

## Job: AIOS-Inv-Evening

- status: active
- schedule: 毎日 21:10
- entrypoint: `scripts/run_ops_scheduler.py --slot inv-evening --date YYYY-MM-DD`
- 目的:
  - 引け後～夜の投資監視データを更新する
- 処理内容:
  - 投資サイクル実行（引け後の再評価）
  - `scripts/investment/backtest/analyze_exit_timing.py --out-date YYYY-MM-DD --mode all`
  - `scripts/investment/backtest/analyze_paper_trade_stats.py --out-date YYYY-MM-DD --mode all`
  - `scripts/notify/render_paper_stats_discord_message.py --date YYYY-MM-DD --fallback-days 3`
  - `scripts/investment/backtest/analyze_watch_promotion.py --out-date YYYY-MM-DD`
  - `scripts/investment/backtest/generate_trade_watch_weekly_review.py --out-date YYYY-MM-DD`

---

## Job: AIOS-Inv-Scenario-0810

- status: planned
- schedule: 平日 08:10（土日スキップ）
- entrypoint: `scripts/run_ops_scheduler.py --slot inv-scenario --date YYYY-MM-DD`
- 目的:
  - 人手注文前の寄り前シナリオを生成する
- 処理内容:
  - `scripts/investment/collect/load_rakuten_board_snapshot.py --date YYYY-MM-DD`（任意。CSVがあれば板スナップショット化）
  - `scripts/investment/signals/build_opening_scenarios.py --date YYYY-MM-DD --fallback-days 3`
  - `scripts/notify/render_opening_scenarios_discord_message.py --date YYYY-MM-DD --fallback-days 3`
  - 出力:
    - `topics/investment-research/inbox/YYYY-MM-DD-board-snapshot.json`（CSVがある場合）
    - `topics/investment-research/inbox/YYYY-MM-DD-opening-scenarios.md`
    - `topics/investment-research/inbox/YYYY-MM-DD-opening-scenarios.json`
    - `prompts/opening-scenarios-discord-message.txt`
  - 入力CSV（楽天RSS想定）:
    - `data/rakuten_rss/board_latest.csv`
    - ヘッダ例: `ticker,company,best_bid,best_ask,indicative_open`

---

## Job: AIOS-Inv-Signal-Post

- status: planned
- schedule: Morning/Noon/Evening の直後（例: 07:35 / 12:15 / 21:15）
- entrypoint: `scripts/notify/post_signal_discord.ps1`（Windowsローカル）
- 目的:
  - 生成済みシグナル通知文を Discord に投稿する
- 処理内容:
  - `.env` から `DISCORD_SIGNAL_WEBHOOK_URL` を読込
  - `prompts/market-signals-discord-message.txt` を POST

---

## Job: AIOS-Inv-Scenario-Post

- status: active（`AIOS-Inv-Scenario-0810` 内で実行）
- schedule: 08:11（Scenario生成直後）
- entrypoint: `scripts/notify/post_scenario_discord.ps1`（Windowsローカル）
- 目的:
  - 寄り前シナリオ通知文を Discord に投稿する
- 処理内容:
  - `.env` から `DISCORD_WEBHOOK_URL` を読込
  - `prompts/opening-scenarios-discord-message.txt` を POST

---

## Job: AIOS-Alert-Healthcheck

- status: active
- schedule: 毎日 21:20
- entrypoint: `scripts/ops/run_alert_and_post.ps1`（Windowsローカル）
- 目的:
  - 欠損/未実行アラートを Discord 通知する
- 処理内容:
  - `scripts/check_daily_missing.py --date today --days 7 --check-db --check-discord-posts --warn-only-soft`
  - `scripts/check_scheduler_health.py --hours 48`
  - `.env` から `DISCORD_ALERT_WEBHOOK_URL` を読込
  - `prompts/pending-daily/latest.status.txt` + `prompts/scheduler-health.status.txt` を POST

---

## Job: AIOS-Generic-Daily-Post

- status: active（`AIOS-Night` 内で実行）
- schedule: Night直後（例: 21:05）
- entrypoint: `scripts/notify/post_generic_discord.ps1`（Windowsローカル）
- 目的:
  - 汎用トピックの日次要約を Discord に投稿する
- 処理内容:
  - `.env` から `DISCORD_GENERIC_WEBHOOK_URL` を読込
  - `prompts/generic-topics-discord-message.txt` を POST

---

## Add Template

新規ジョブを追加するときは、以下テンプレをコピーしてください。

```md
## Job: <TaskName>

- status: active
- schedule: <毎日 HH:MM / 毎週 ...>
- entrypoint: <実行コマンド>
- 目的:
  - <何のためのジョブか>
- 処理内容:
  - <スクリプト1>
  - <スクリプト2>
  - <必要なら補足>
```
## Job: AIOS-Backtest-Weekly

- status: active
- schedule: 毎週日曜 03:30
- entrypoint: `scripts/ops/run_backtest_weekly.ps1`
- 目的:
  - バックテスト補完を定期実行し、`investment.db` へ取り込む
- 処理内容:
  - `scripts/investment/backtest/run_backtest_suite.py --mode deep --date YYYY-MM-DD`
  - `scripts/data/init_investment_db.py`
  - `scripts/data/ingest_investment_db.py --date YYYY-MM-DD`
  - `scripts/investment/backtest/analyze_exit_timing.py --out-date YYYY-MM-DD --mode all`
  - `scripts/investment/backtest/analyze_paper_trade_stats.py --out-date YYYY-MM-DD --mode all`
  - `scripts/investment/backtest/analyze_watch_promotion.py --out-date YYYY-MM-DD`
  - `scripts/investment/backtest/generate_trade_watch_weekly_review.py --out-date YYYY-MM-DD`

## 再登録ポリシー（重要）

- 公式再登録スクリプト: `scripts/ops/register_tasks.ps1`
- 設定:
  - `WakeToRun = true`（スリープ解除して実行）
  - `StartWhenAvailable = true`（取りこぼし後の追随実行）
