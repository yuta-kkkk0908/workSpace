# workSpace 自律改善システム

## 目的

workSpace を、単なる情報収集基盤ではなく、

- 改善候補を自動で収集する
- AI が論点を整理する
- 優先度の高いものを proposal として整理する
- Codex が proposal DB を起点に実装候補を作る

ところまでつなぐ、自律改善ループへ育てる。

## 現状の前提

- DB-first を前提にする
- 正本は DB、ファイルは監査ログまたはフォールバック
- AI は新規事実を作らない
- 失敗時は既存の収集・通知を止めない
- 人間レビューを必須にして、本番マージは自動化しない

## 既存の足場

すでに以下の AI ジョブがある。

- `AIOS-Inv-AI-2100`
- `AIOS-Inv-Scenario-0810`
- `AIOS-Night`

関連する既存の AI ステージは以下。

- `generate_ai_investment_digest.py`
- `analyze_signal_quality_alert_ai.py`
- `review_scenario_promotion_ai.py`
- `generate_ai_analyst_report.py`
- `generate_weekly_tuning_ai_review.py`

## 実装方針

「自動改修」ではなく、

改善案発見 → 論点整理 → proposal化 → work item化 → claim → PR作成

の流れを安定して回す。

## フェーズ1 改善候補収集

### 目的

改善の芽を、毎週・毎日で拾って蓄積する。

### 新規テーブル

`improvement_candidate`

- 保存先: `data/ops.db`
- 監査実行の記録: `improvement_audit_runs`

### 想定項目

- `id`
- `title`
- `category`
- `source`
- `description`
- `impact_score`
- `effort_score`
- `priority`
- `status`
- `created_at`
- `updated_at`

### 登録元

- エラーログ
- Discord通知分析
- 投資シナリオ分析
- note記事分析
- ニーズ収集結果
- AI監査レポート

### 運用メモ

- 同一件の重複登録を避ける
- `source` と `description` に根拠を残す
- 候補の更新履歴を追える形にする

## フェーズ2 AI監査官

### 目的

週次で改善候補を見つけ、`improvement_candidate` に保存する。

### 実行

- `scripts/investment/analysis/generate_improvement_audit.py`
- 毎日 06:00 の改善ジョブで実行する

### 入力

- エラーログ
- Discord通知ログ
- 投資DBの主要テーブル
- ニーズDBの分析結果
- 既存の AI レポート出力

### 出力

- 今週の改善候補 TOP10
- 重複通知
- エラー発生傾向
- 利用されていない機能
- シナリオ精度低下
- 記事 PV 分析

### 原則

- 推測しない
- 不明は不明と書く
- 既存の集計値がある場合のみ使う
- AI の判断結果は、必ず後で追跡できるように保存する

## フェーズ3 Proposal 自動生成

### 目的

優先度が一定以上の改善候補を proposal として整理し、DB に蓄積する。

### 保存先

- proposal table: `improvement_proposals` (`data/ops.db`)
- proposal の正本は DB
- Discord の `codex-log` は通知・確認の場として使う
- `improvement_work_items` は `work_plan_json` / `target_files_json` / `validation_commands_json` を持つ
- `improvement_work_items` は実装結果を `execution_result_json` / `validation_result_json` / `changed_files_json` / `diff_summary_json` に書き戻す
- `improvement_work_items` は関連した監査ログIDを `audit_log_ids_json` に持つ
- 監査ログは `improvement_audit_log` に append-only で保存する

### 監査ログの保存項目

`improvement_audit_log` には、work item ごとの段階別スナップショットを残す。

- `work_item_id`
- `proposal_id`
- `candidate_date`
- `source_key`
- `attempt_no`
- `stage`
- `round_no`
- `event_type`
- `status`
- `summary`
- `blocked_reason`
- `input_json`
- `output_json`
- `validation_json`
- `review_json`
- `branch_name`
- `commit_sha`
- `pr_url`
- `created_at`

保存方針:

- `execution` / `validation` / `review` / `final` を stage として記録する
- 1回の実行で複数ラウンド回した場合は round ごとに残す
- 失敗時も final の監査行を残す
- 途中で参照したプロンプトや検証結果は JSON で保持する
- work item 本体は状態管理、監査ログは証跡保存に使う

### Proposal テンプレート

- 現象
- 原因候補
- 改善案
- 期待効果
- 実装対象ファイル候補

### 判断基準

- priority が高いものを優先
- 既存 proposal の重複を避ける
- 対応済みの候補は再起票しない

### 実行

- `scripts/investment/analysis/generate_improvement_proposals.py`
- 毎日 06:00 の改善ジョブで改善監査の直後に実行する
- `DISCORD_CODEX_LOGER_CHANNEL_HOOK` がある環境では `codex-log` に投稿し、ない場合も DB に proposal を積む
- その後、proposal を `improvement_work_items` に materialize して着手対象にする
- `improvement_work_items` は `open -> doing -> done` で進める

## フェーズ4 Codex 連携

### 目的

proposal を元に、Codex CLI が改修・検証までを担う。

### 実施内容

- Codex CLI でコード変更
- 必要なテストや確認の実施
- 実行結果の DB 書き戻し

### 着手

- `scripts/investment/analysis/materialize_improvement_work_items.py`
- 毎日 06:00 の改善ジョブで proposal を work item に昇格する
- `scripts/investment/analysis/claim_improvement_work_items.py`
- 毎日 06:00 の改善ジョブで open work item を claim する
- `scripts/investment/analysis/execute_improvement_work_items.py`
- `doing` work item を読んで Codex CLI で改修・検証し、結果を DB に書き戻す
- `ENABLE_IMPROVEMENT_EXECUTION=1` のときのみ scheduler から自動実行する
- 実行時は一時 worktree を作り、通常は自動削除する。保持したい場合は `KEEP_IMPROVEMENT_WORKTREE=1`
- 着手の正本は `improvement_work_items`

### 制約

- 本番マージは禁止
- 必ず人間レビューを通す
- 失敗時も、他の運用ジョブを止めない

## フェーズ5 自律改善ダッシュボード

### 表示項目

- 未対応改善件数
- 改善実施件数
- 改善効果
- シナリオ精度推移
- 記事 PV 推移
- Discord 利用状況

### 目的

改善の「出しっぱなし」を防ぎ、蓄積と効果測定を一体で見られるようにする。

## 成功条件

- 毎週改善候補が自動生成される
- 改善候補が DB に蓄積される
- proposal が DB で追跡できる
- work item が DB に作成される
- Codex CLI が改修・検証結果まで DB に残す
- 人間は承認判断に集中する

## 最終目標

「自動改修」ではなく、

改善案発見 → proposal 整理 → 実装提案 → Codex CLI による改修・検証の書き戻し

の自律サイクルを確立すること。
