# OPERATION_CURRENT.md

# 現行運用（As-Is）

## 位置づけ

- このドキュメントは「今どう動いているか」の実行手順を管理する。
- 展望・方針は `doc/OPERATION.md` を参照する。

## 定期実行ジョブ

- 夜バッチ: `AIOS-Night`
- 投資バッチ: `AIOS-Inv-Morning` / `AIOS-Inv-Noon` / `AIOS-Inv-Evening`
- シナリオ: `AIOS-Inv-Scenario-0810`
- アラート: `AIOS-Alert-Healthcheck`（planned）
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

## 取り逃し対応

- 欠損検知: `scripts/check_daily_missing.py`
- 補完プロンプト: `prompts/pending-daily/latest.prompt.md`
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
- Scenario通知:
  - 元データ: `prompts/opening-scenarios-discord-message.txt`
  - 送信先: `DISCORD_WEBHOOK_URL`
- Alert通知:
  - 元データ: `prompts/pending-daily/latest.status.txt`
  - 送信先: `DISCORD_ALERT_WEBHOOK_URL`
- Generic Daily通知:
  - 元データ: `prompts/generic-topics-discord-message.txt`
  - 送信先: `DISCORD_GENERIC_WEBHOOK_URL`
