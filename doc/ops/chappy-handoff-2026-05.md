# Chappy運用サマリ（2026-05）

このドキュメントは、Chappyが現行構成を短時間で共有できるようにしたハンドオフ用要約。

## 1) 運用の基本方針

- DB-first を厳守する（判定・通知の正本はDB）
- ファイル（`topics/*/inbox/*`, `prompts/*`）は監査ログまたはフォールバック用途
- 原則: **DB保存成功 → 必要なら通知用テキスト生成**、DB失敗時のみファイル経路へ退避

参照:
- `doc/OPERATION_CURRENT.md`
- `doc/topic-db-design.md`
- `doc/investment-db-unified-schema.md`

## 2) 主要DB

- 非投資トピック: `data/topics.db`
  - `topic_daily_digest`, `topic_links`, `topic_ai_summaries`
- 投資: `data/investment.db`
  - `signals`, `entry_candidates`, `opening_scenarios`, `paper_trades`, `daily_digest`, `collection_artifacts`
- ニーズ: `data/needs.db`
- 運用ログ: `data/ops.db`

## 3) 定期ジョブ（要点）

- `AIOS-Night`（毎日21:00）
  - 汎用トピック収集、topics/needs/investment DB更新、generic通知文生成
  - ポケカAI要約 + ポケカ記事重複統合（AI）
  - 週次AIレビュー（月曜のみ）
- `AIOS-Inv-Morning` / `AIOS-Inv-Noon` / `AIOS-Inv-Evening`
  - 投資収集・シグナル生成・候補生成・DB更新
  - `check_signal_quality` 後に ALERT 時だけAIトリアージ
- `AIOS-Inv-Scenario-0810`
  - 寄り前シナリオ生成、昇格/見送りレビュー（AI）
- `AIOS-Inv-AI-2100`
  - 投資分析サマリ（AI）生成・Discord投稿

詳細台帳:
- `doc/scheduler-job-catalog.md`

## 4) AI適用ポイント（現行）

1. 投資日次分析（21:00）
- `scripts/investment/analysis/generate_ai_investment_digest.py`
- 保存先: `investment.db` `daily_digest(topic='ai-investment-digest')`

2. シグナル品質アラート時トリアージ
- `scripts/investment/analysis/analyze_signal_quality_alert_ai.py`
- 発火条件: `signal-quality-metrics.status == ALERT`
- 保存先: `investment.db` `collection_artifacts(artifact_key='signal_quality_ai_triage')`

3. シナリオ昇格レビュー
- `scripts/investment/analysis/review_scenario_promotion_ai.py`
- 保存先: `investment.db` `collection_artifacts(artifact_key='scenario_promotion_ai_review')`

3.5. AI分析官レポート（論点整理）
- `scripts/investment/analysis/generate_ai_analyst_report.py`
- 件数: LONG3 / SHORT3 / WATCH3
- 保存先: `investment.db` `collection_artifacts(artifact_key='ai_analyst_report')`
- 通知: `render_opening_scenarios_discord_message.py` が既存シナリオ通知へ要約を追記

4. ポケカ要約
- `scripts/topics/enrich_pokemon_daily_with_ai.py`
- 保存先: `topics.db` `topic_ai_summaries(kind='collection_summary')`

5. ポケカ記事重複統合
- `scripts/topics/consolidate_pokemon_sources_ai.py`
- 保存先: `topics.db` `topic_ai_summaries(kind='dedupe_summary')`

6. 週次チューニングAIレビュー（月曜のみ）
- `scripts/investment/analysis/generate_weekly_tuning_ai_review.py`
- 保存先: `investment.db` `collection_artifacts(artifact_key='weekly_tuning_ai_review')`

## 5) モデル・ジョブ設定ファイル

- モデルルーティング:
  - `configs/ai_model_routing.json`
- ジョブ別AI具体設定:
  - `configs/ai_job_settings.json`

## 6) 通知系のDB-first状況（現時点）

- DB-first:
  - `render_market_signals_discord_message.py`
  - `render_opening_scenarios_discord_message.py`
  - `render_generic_topics_discord_message.py`
  - `render_ops_kpi_summary_discord_message.py`
  - `render_paper_stats_discord_message.py`（DB優先 + ファイルフォールバック）
  - `render_ai_investment_digest_from_db.py`

## 7) 変更時のチェックポイント

- `run_ops_scheduler.py` に差し込んだAIステージが `allow_fail=True` か確認
- DB保存先テーブルの upsert キーが安定しているか確認
- `doc/scheduler-job-catalog.md` と設定JSON（model/job）を同時更新
- 重要: DB-first契約を崩さない（先にDB、失敗時のみファイル）

## 8) Chappyへの最短共有テンプレ

「この環境はDB-first運用。通知・判定の正本は `topics.db` / `investment.db`。  
AIは jobごとに `configs/ai_model_routing.json` と `configs/ai_job_settings.json` で管理。  
主要ジョブと実行順は `doc/scheduler-job-catalog.md`、現行運用は `doc/OPERATION_CURRENT.md` を正として参照。」
