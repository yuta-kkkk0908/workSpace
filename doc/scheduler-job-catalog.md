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
    - `scripts/topics/enrich_pokemon_daily_with_ai.py --date YYYY-MM-DD`（ポケカ収集メモへAI要約付与）
    - `scripts/topics/consolidate_pokemon_sources_ai.py --date YYYY-MM-DD`（ポケカ記事重複統合）
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
    - `scripts/investment/collect/collect_jpx_daily_pdf_prices.py --date YYYY-MM-DD`（JPX日足PDF）
    - `scripts/investment/signals/check_investment_signal_missing.py --date YYYY-MM-DD`  
    - `scripts/investment/signals/generate_entry_candidates.py --date YYYY-MM-DD`  
    - `scripts/data/init_investment_db.py`  
    - `scripts/data/ingest_investment_db.py --date YYYY-MM-DD`  
    - `scripts/data/build_today_brief_from_db.py --date YYYY-MM-DD`
    - outcomesバックフィル（実取得あり）
      - 30日: 毎日
      - 90日: 毎週月曜
      - 180日: 毎月1日
  - 週次AIレビュー（月曜のみ）
    - `scripts/investment/analysis/generate_weekly_tuning_ai_review.py --date YYYY-MM-DD`

## Job: AIOS-Improvement-0600

- status: active
- schedule: 毎日 06:00
- entrypoint: `scripts/ops/run_improvement_0600.ps1`
- 目的:
  - 改善候補の proposal 化と work item 化を日次で回す
  - 実装可能なものは朝のうちに claim まで進める
- 処理内容:
  - `scripts/investment/analysis/generate_improvement_audit.py --date YYYY-MM-DD`（改善候補を `ops.db` に蓄積）
  - `scripts/investment/analysis/generate_improvement_proposals.py --date YYYY-MM-DD`（改善候補を proposal 化して `codex-log` に投稿）
  - `scripts/investment/analysis/materialize_improvement_work_items.py --date YYYY-MM-DD`（proposal を work item 化して着手対象にする）
  - `scripts/investment/analysis/claim_improvement_work_items.py --date YYYY-MM-DD`（open work item を doing に引き上げる）
  - `scripts/investment/analysis/execute_improvement_work_items.py --date YYYY-MM-DD`（`ENABLE_IMPROVEMENT_EXECUTION=1` のときのみ Codex CLI で doing work item を改修・検証する。`GITHUB_TOKEN` があれば commit/push して draft PR まで自動作成し、なくてもローカル commit までは進める。通常は一時 worktree を自動削除し、保持したい場合は `KEEP_IMPROVEMENT_WORKTREE=1`）

## Job: AIOS-Inv-Morning

- status: active
- schedule: 毎日 07:30
- entrypoint: `scripts/run_ops_scheduler.py --slot inv-morning --date YYYY-MM-DD`
- 目的:
  - 朝の投資監視データを更新する
  - TDnet 適時開示の朝用ダイジェストと note 下書き保存も含めて完了させる
- 処理内容:
  - 投資サイクル実行
    - `scripts/investment/signals/prepare_morning_market_signals.py --date YYYY-MM-DD --fallback-days 3`
    - `scripts/investment/signals/check_investment_signal_missing.py --date YYYY-MM-DD`
    - `scripts/investment/signals/generate_entry_candidates.py --date YYYY-MM-DD --fallback-days 3`
    - `scripts/data/init_investment_db.py`
    - `scripts/data/ingest_investment_db.py --date YYYY-MM-DD`
    - `scripts/data/build_today_brief_from_db.py --date YYYY-MM-DD`
    - `scripts/investment/analysis/analyze_signal_quality_alert_ai.py --date YYYY-MM-DD`（ALERT時のみ）
    - `scripts/notify/render_market_signals_discord_message.py --date YYYY-MM-DD --fallback-days 3`
  - 後段ポスト
    - `scripts/ops/do_inv_morning_and_post.ps1`
    - `scripts/run_ops_scheduler.py --slot inv-morning --date YYYY-MM-DD` の内部で TDnet 朝ダイジェスト生成と note 下書き保存を実行する

---

## Job: AIOS-Inv-Noon

- status: active
- schedule: 毎日 12:10
- entrypoint: `scripts/run_ops_scheduler.py --slot inv-noon --date YYYY-MM-DD`
- 目的:
  - 昼時点の投資監視データを再更新する
- 処理内容:
  - `scripts/investment/collect/collect_intraday_signal_snapshots.py --date YYYY-MM-DD --slot inv-noon`
  - `scripts/investment/signals/reevaluate_market_signals_noon.py --date YYYY-MM-DD --slot inv-noon`
  - `scripts/investment/analysis/analyze_signal_quality_alert_ai.py --date YYYY-MM-DD`（ALERT時のみ）
  - noon再評価は `gate/score` 分離:
    - 逆行強/欠損は `hold_noon_recheck`
    - 理由コードは `signals.payload_json.noonReeval` に保存

---

## Job: AIOS-Inv-Evening

- status: active
- schedule: 毎日 17:00
- entrypoint: `scripts/run_ops_scheduler.py --slot inv-evening --date YYYY-MM-DD`
- 目的:
  - 引け後～夜の投資監視データを更新する
- 処理内容:
  - 投資サイクル実行（引け後の再評価）
  - `scripts/investment/backtest/fill_market_outcomes.py --date YYYY-MM-DD --seed-list rough_backtest_full --include-db-signals`
  - `scripts/investment/backtest/analyze_exit_timing.py --out-date YYYY-MM-DD --mode all`
  - `scripts/investment/backtest/analyze_paper_trade_stats.py --out-date YYYY-MM-DD --mode all`
  - `scripts/notify/render_paper_stats_discord_message.py --date YYYY-MM-DD --fallback-days 3`
  - `scripts/investment/backtest/analyze_watch_promotion.py --out-date YYYY-MM-DD`
  - `scripts/investment/backtest/generate_trade_watch_weekly_review.py --out-date YYYY-MM-DD`
  - `scripts/investment/analysis/analyze_signal_quality_alert_ai.py --date YYYY-MM-DD`（ALERT時のみ）

---

## Job: AIOS-Inv-AI-2100

- status: active
- schedule: 毎日 21:00
- entrypoint: `scripts/ops/run_inv_ai_2100_and_post.ps1`（Windowsローカル）
- 目的:
  - 投資DB更新のうえで、AI要約を生成しDiscordへ投稿する
  - 失敗時にアラート通知まで一気通貫で実行する
- 処理内容:
  - `scripts/run_ops_scheduler.py --slot inv-evening --date YYYY-MM-DD`
  - `scripts/notify/resend_pending_discord.ps1`
  - `scripts/notify/post_signal_discord.ps1`
  - `scripts/investment/analysis/generate_ai_investment_digest.py --date YYYY-MM-DD`
  - `scripts/notify/post_ai_investment_digest_discord.ps1`
  - いずれか失敗時: `scripts/notify/post_alert_discord.ps1`
  - ドライラン:
    - 初回実行日から2日間は `--dry-run` で AI本文生成を擬似実行
    - 状態ファイル: `prompts/.inv-ai-2100-dry-run-start.txt`

---

## Job: AIOS-Inv-Scenario-0810

- status: planned
- schedule: 平日 08:10（土日スキップ）
- entrypoint: `scripts/run_ops_scheduler.py --slot inv-scenario --date YYYY-MM-DD`
- 目的:
  - 人手注文前の寄り前シナリオを生成する
- 処理内容:
  - `scripts/investment/analysis/generate_ai_analyst_report.py --date YYYY-MM-DD`（分析官レポートをDB保存）
  - `scripts/investment/analysis/review_scenario_promotion_ai.py --date YYYY-MM-DD`（昇格/見送りレビュー）
  - `scripts/investment/signals/build_opening_scenarios.py --date YYYY-MM-DD --fallback-days 3`
  - `scripts/notify/render_opening_scenarios_discord_message.py --date YYYY-MM-DD --fallback-days 3`
  - 出力:
    - `topics/investment-research/inbox/YYYY-MM-DD-opening-scenarios.md`
    - `topics/investment-research/inbox/YYYY-MM-DD-opening-scenarios.json`
    - `prompts/opening-scenarios-discord-message.txt`

---

## Job: AIOS-Inv-Signal-Post

- status: planned
- schedule: Morning/Noon/Evening の直後（例: 07:35 / 12:15 / 21:15）
- entrypoint: `scripts/notify/post_signal_discord.ps1`（Windowsローカル）
- 目的:
  - 生成済みシグナル通知文を Discord に投稿する
- 処理内容:
  - `.env.local` から `DISCORD_SIGNAL_WEBHOOK_URL` を読込
  - `prompts/market-signals-discord-message.txt` を POST

---

## Job: AIOS-Inv-Scenario-Post

- status: active（`AIOS-Inv-Scenario-0810` 内で実行）
- schedule: 08:11（Scenario生成直後）
- entrypoint: `scripts/notify/post_scenario_discord.ps1`（Windowsローカル）
- 目的:
  - 寄り前シナリオを `シナリオスレッド` チャンネルへスレッド形式で投稿する
- 処理内容:
  - `.env.local` から `DISCORD_SCENARIO_CHANNEL_ID` と Bot token を読込
  - `scripts/notify/post_scenarios_bot.py --date YYYY-MM-DD` を実行
  - 1シナリオごとに:
    - 親チャンネルへアンカー投稿
    - その投稿から public thread を作成
    - thread 内へ詳細本文を投稿
  - `scenario_messages` に `thread_id / anchor_message_id / message_id` を記録

---

## Job: AIOS-Scenario-Replies-Sync

- status: active
- schedule: 定期poll（Task Scheduler 登録値に従う）
- entrypoint: `scripts/ops/run_sync_scenario_replies.ps1`
- 目的:
  - シナリオスレッド内の `entry / exit / cancel / credit` 指示を DB に反映する
- 処理内容:
  - `.env.local` から `DISCORD_SCENARIO_CHANNEL_ID` と Bot token を読込
  - 親チャンネルの active threads を列挙
  - 各スレッドの最新メッセージを取得
  - `scenario_messages.thread_id` で対象シナリオを解決
  - `paper_trades` / `credit_status_rows` / `scenario_reply_events` を更新

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
  - `scripts/check_scheduler_health.py --mode weekly --hours 168`（月曜のみ）
  - `scripts/check_needs_freshness.py`（水曜のみ）
  - `.env.local` から `DISCORD_ALERT_WEBHOOK_URL` を読込
  - `prompts/pending-daily/latest.status.txt` + `prompts/scheduler-health.status.txt` を POST
  - 水曜のみ `prompts/needs-freshness.status.txt` を同梱して POST
  - Alert本文セクション:
    - `[DATA_INGEST / DAILY_COVERAGE]`
    - `[SCHEDULER_RUNTIME]`
    - `[SCHEDULER_WEEKLY]`（週次生成時）
    - `[NEEDS_WEEKLY_FRESHNESS]`（水曜）

---

## Job: AIOS-Generic-Daily-Post

- status: active（`AIOS-Night` 内で実行）
- schedule: Night直後（例: 21:05）
- entrypoint:
  - forum優先: `scripts/notify/post_generic_forum_discord.ps1`
  - fallback: `scripts/notify/post_generic_threads_discord.ps1`
- 目的:
  - 汎用トピックの日次要約を Discord の固定topic forum post へ蓄積する
- 処理内容:
  - `.env.local` から `DISCORD_GENERIC_FORUM_CHANNEL_ID` または `DISCORD_GENERIC_CHANNEL_ID` と `DISCORD_TASKS_BOT_TOKEN` を読込
  - `prompts/generic-topics-discord-message.txt` を解析
  - forum運用時は topic固定 forum post (`ai-news-watch` / `pokemon-card-watch` / `tech-stack-reads`) を維持
  - 各topicへ `YYYY-MM-DD` 日次内容を追記
  - 状態は `prompts/generic-forum-state.json` で管理
  - fallback の thread互換運用では `prompts/generic-threads-state.json` を使用
  - 2026-05-26: 古いアンカー編集で Discord `429 code=30046` が発生したため、forum優先に変更

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

---

## Job: AIOS-Data-Harvest

- status: active
- schedule: 毎日 23:40
- entrypoint: `scripts/ops/run_data_harvest.ps1`
- 目的:
  - 収集を手動依存から外し、日次で母数を増やし続ける
  - TDnet/Kabutan/結果補完/DB取り込みを1ジョブで連続実行する
- 処理内容:
  - `scripts/investment/collect/run_harvest_backfill.py --end-date YYYY-MM-DD --days 21 --discover-latest 120 --max-pages 120 --tdnet-max-items 800 --seed-list rough_backtest_full`
  - 内部で以下を日付ループ実行:
    - `scripts/investment/collect/collect_jpx_daily_pdf_prices.py`（対象日付のJPX相場表PDF）
    - `scripts/investment/collect/collect_tdnet_disclosures.py`
    - `scripts/investment/collect/collect_kabutan_surprise_signals.py`
    - `scripts/investment/collect/collect_kabutan_short_signals.py`
    - `scripts/investment/backtest/fill_market_outcomes.py --include-db-signals`
    - `scripts/investment/signals/build_market_signals_from_batches.py`
    - `scripts/data/ingest_investment_db.py`

---

## Job: AIOS-DB-Backup-2230

- status: active
- schedule: 毎日 02:00
- entrypoint: `scripts/ops/run_db_backup_to_discord.ps1`
- 目的:
  - `investment.db` のフルバックアップを日次で保全する
  - Discord にZIP保管し、障害時のロールバック起点を確保する
- 処理内容:
  - `scripts/data/backup_dbzip_to_discord.py --db data/investment.db --label investment-db-backup --keep-local 14`
  - DBスナップショットを `investment.db` 名でZIP化
  - `DISCORD_BACKUPPER_URL` へファイル添付投稿
  - 投稿結果（`message_id/channel_id/attachment_url`）を `data/backups/discord-backups-manifest.json` に記録
  - ローカルZIPは最新14件のみ保持
- 復元手順:
  - `scripts/data/restore_dbzip_from_discord.py --channel-id <id> --message-id <id>`
  - channel/message未指定時は manifest の最新投稿を利用
  - 復元前に現行DBを `investment.db.pre-restore-YYYYMMDD-HHMMSS` として退避
  - ZIP内DBが壊れている場合は `recover_investment_db.py` で救済して反映

## 再登録ポリシー（重要）

- 公式再登録スクリプト: `scripts/ops/register_tasks.ps1`
- 設定:
  - `WakeToRun = true`（スリープ解除して実行）
  - `StartWhenAvailable = true`（取りこぼし後の追随実行）
