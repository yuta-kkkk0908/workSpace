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
  - 元データ: `prompts/opening-scenarios-discord-message.txt`
  - 送信先: `DISCORD_WEBHOOK_URL`
- Alert通知:
  - 元データ: `prompts/pending-daily/latest.status.txt`
  - 追加データ: `prompts/scheduler-health.status.txt`
  - 送信先: `DISCORD_ALERT_WEBHOOK_URL`
- Generic Daily通知:
  - 元データ: `prompts/generic-topics-discord-message.txt`
  - 送信先: `DISCORD_GENERIC_WEBHOOK_URL`
## 2026-05 運用修正

- `inv-scenario` は土日スキップ（休場のため）
- `night` で `collect_generic_daily_topics.py` を実行し、汎用トピックの当日ファイルを自動生成
- タスク再登録は `scripts/ops/register_tasks.ps1` を使用（`WakeToRun` / `StartWhenAvailable` を強制）

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
