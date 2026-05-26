# OPERATION_CURRENT.md

# 現行運用（As-Is）

## 位置づけ

- このドキュメントは「今どう動いているか」の実行手順を管理する。
- 展望・方針は `doc/OPERATION.md` を参照する。

## 定期実行ジョブ

- 夜バッチ: `AIOS-Night`
- 投資バッチ: `AIOS-Inv-Morning` / `AIOS-Inv-Noon` / `AIOS-Inv-Evening`
- シナリオ: `AIOS-Inv-Scenario-0810`
- 週次バックテスト: `AIOS-Backtest-Weekly`
- アラート: `AIOS-Alert-Healthcheck`
- 詳細: `doc/scheduler-job-catalog.md`

## データ保存先

- 非投資daily: `data/topics.db`
- ニーズ: `data/needs.db`
- 投資: `data/investment.db`
- 原本: `topics/*/inbox/*`

## Daily運用（必須）

1. DB-first で確認する
2. DB不足時のみ inbox 補完参照
3. 回答時に「DB確認済み / 補完有無」を明示

参照:
- `commands/daily.md`
- `AGENT.md`

## 投資朝バッチの補足

- `inv-morning / inv-noon / inv-evening` の候補生成は `generate_entry_candidates.py` を使用
- 当日 `market-signals` が未作成でも、最大3日まで過去 `market-signals` をフォールバック参照して候補生成する
- これにより「朝タスク成功なのに候補0件（入力欠損）」を減らす
- `inv-evening` では追加で次を日次更新する
  - `paper-exit-timing`（保有期間別傾向）
  - `paper-stats`（`backtest/watch/live` のモード比較）
  - `watch-promotion`（watch→trade昇格候補）
    - `Ladder` 運用: `strict > balanced > early > none` で WATCH 優先度を扱う
  - `trade-watch-review`（trade/watch 差分レビュー）

## 取り逃し対応

- 欠損検知: `scripts/check_daily_missing.py`
- Scheduler健全性: `scripts/check_scheduler_health.py`
- 補完プロンプト: `prompts/pending-daily/latest.prompt.md`
- Health出力: `prompts/scheduler-health.status.txt`
- 補完後: 各DBへ再投入

## 役割分担

- Python:
  - 定期収集
  - 欠損検知
  - DB投入
  - 定型集計
- Codex:
  - 今日の情報要約
  - 分析
  - ルール改定支援

## 変更時に更新するファイル

- `doc/scheduler-job-catalog.md`
- `doc/ops-flow-overview.md`
- `doc/OPERATION_CURRENT.md`
- 必要に応じて `commands/*.md`

## Discord通知（運用メモ）

- このRepoでは `inv-scenario` 実行時に以下を生成する:
  - `prompts/opening-scenarios-discord-message.txt`
- このRepoでは `inv-morning/noon/evening` 実行時に以下を生成する:
  - `prompts/market-signals-discord-message.txt`
  - `prompts/paper-stats-discord-message.txt`（evening）
- このRepoでは `night` 実行時に以下を生成する:
  - `prompts/generic-topics-discord-message.txt`
- Webhook URLは `.env` に保存する:
  - `DISCORD_WEBHOOK_URL=...`
  - `DISCORD_SIGNAL_WEBHOOK_URL=...`
  - `DISCORD_ALERT_WEBHOOK_URL=...`
  - `DISCORD_GENERIC_WEBHOOK_URL=...`
- `.env` はコミットしない（`.gitignore` 対象）

## 通知チャネルの整理

- Signal通知:
  - 元データ: `prompts/market-signals-discord-message.txt`
  - 送信先: `DISCORD_SIGNAL_WEBHOOK_URL`
- Paper Stats通知:
  - 元データ: `prompts/paper-stats-discord-message.txt`
  - 送信先: `DISCORD_STATS_WEBHOOK_URL`（未設定時は `DISCORD_SIGNAL_WEBHOOK_URL`）
- Scenario通知:
  - 送信先: `DISCORD_SCENARIO_CHANNEL_ID`（Bot投稿 / `1508104046030880899`）
  - 実装: `scripts/notify/post_scenarios_bot.py`
  - 運用:
    - チャンネル `シナリオスレッド` では 1シナリオ = 1アンカー投稿 + 1スレッド
    - エントリー/イグジット/credit 応答は各スレッド内で受ける
    - シナリオ解決は `scenario_messages.thread_id` で行う
    - `trade` シナリオは投稿時に `paper_trades.mode='paper'` へ自動登録して事後成績を追跡する
    - 手動 `entry paper` / `entry 机上` は補助用途（watchや個別観測用）
    - 返信同期は `scripts/notify/sync_scenario_replies_bot.py` が active threads を読んで DB 反映する
- Alert通知:
  - 元データ: `prompts/pending-daily/latest.status.txt`
  - 追加データ: `prompts/scheduler-health.status.txt`
  - 週次追加データ（水曜のみ）: `prompts/needs-freshness.status.txt`
  - 送信先: `DISCORD_ALERT_WEBHOOK_URL`
- Generic Daily通知:
  - 元データ: `prompts/generic-topics-discord-message.txt`
  - 送信先:
    - 既定: `DISCORD_GENERIC_CHANNEL_ID`（Bot投稿 / thread互換）
    - forum運用時: `DISCORD_GENERIC_FORUM_CHANNEL_ID=1508808144753791006`
  - 実装:
    - thread互換: `scripts/notify/post_generic_threads_bot.py`
    - forum: `scripts/notify/post_generic_forum_bot.py`
  - 投稿経路メモ:
    - `PowerShell + Invoke-RestMethod` の Discord Bot POST は `40333 internal network error` で不安定
    - Bot投稿は `Python + urllib.request` 経路を優先する
  - 運用:
    - forum ID が設定されている場合は `AIOS-Night` が forum 経路を優先する
    - topicは `ai-news-watch` / `pokemon-card-watch` / `tech-stack-reads`
    - forum では topic ごとに固定 forum post を1本持ち、日次内容を追記する
    - thread互換では固定アンカーを毎日編集しない
    - 同日同内容は再投稿しない
    - 同日の内容更新時は同一スレッドへ `updated` 付きで追記する
  - 障害メモ:
    - 2026-05-26 夜の `AIOS-Night` は generic 投稿で失敗
    - 原因は Discord `429 / code=30046`（1時間以上前の古いメッセージ編集制限）
    - thread互換運用の古いアンカー `PATCH` を止めて回避済み
## 2026-05 運用修正

- `inv-scenario` は土日スキップ（休場のため）
- `night` で `collect_generic_daily_topics.py` を実行し、汎用トピックの当日ファイルを自動生成
- タスク再登録は `scripts/ops/register_tasks.ps1` を使用（`WakeToRun` / `StartWhenAvailable` を強制）

## Alertメッセージ分類（2026-05）

- Alert通知本文は次のセクションで分離して表示する。
  - `[DATA_INGEST / DAILY_COVERAGE]`: daily欠損・DB未投入
  - `[SCHEDULER_RUNTIME]`: 定期実行エラー（task runtime）
  - `[SCHEDULER_WEEKLY]`: 週次ヘルス詳細（毎週月曜に生成）
  - `[NEEDS_WEEKLY_FRESHNESS]`: ニーズ最終取得日（毎週水曜に生成）
- `check_daily_missing.py` の警告は次で表記する。
  - `DATA_INGEST(ERROR)`: 要対応（DB未投入など）
  - `DELIVERY_SOFT(INFO)`: 監視情報（投稿ログ未検知など）

## 投資パイプライン（Python完結）

1. 収集（最新情報の取得）
   - `collect_kabutan_surprise_signals.py`
   - `collect_kabutan_short_signals.py`
2. 一時保存（作業中間成果物）
   - `topics/investment-research/inbox/YYYY-MM-DD-six-month-rough-backtest-batch-5-kabutan-surprise.md`
   - `topics/investment-research/inbox/YYYY-MM-DD-six-month-rough-backtest-batch-6-short-negative.md`
3. 当日シグナル生成
   - `build_market_signals_from_batches.py`
   - 出力: `topics/investment-research/inbox/YYYY-MM-DD-market-signals.md`
4. DB投入
   - `ingest_investment_db.py --date YYYY-MM-DD`
   - 保存先: `data/investment.db`

## 明日以降タスク（投資重点 / 採用済み）

- 詳細タスク一覧は `doc/task/20260519-investment-priority-tasks.md` を参照。

## backtest_outcomes 重複対策運用

- 同一性キーは `source_signal_id + signal_date + signal_type`。
- 取り込み時は上記3項目が必須。欠落行は取り込まない。
- `outcome_id` は取り込み側で決定的に再生成する。

### 既存DBマイグレーション手順

1. 重複件数を確認する（0件でない場合は次へ進む）
2. 同一性キー単位で `updated_at` 最新1件を残し重複削除する
3. `python scripts/data/init_investment_db.py --db data/investment.db` を実行して一意インデックスを適用する
4. `scripts/check_scheduler_health.py` の結果で duplicate alert がないことを確認する

補足:
- `fill_market_outcomes.py` 出力では `sourceSignalId` / `signalDate` / `signalType` を常に出力すること。
- 監視で `backtest_outcomes duplicate identity groups=...` が出た場合は、再度クレンジングを実施する。
