# Scheduler Data Pipeline Plan

## Goal
タスクスケジューラーで定期実行し、情報収集をPython側で自立化する。
Codexは「要約・分析・改修」に集中させ、レート消費を抑える。

## Scope (Current Focus)
- タスクスケジューラー連動の定期収集処理
- 収集後の標準整形（signals / entry candidates / DB投入）
- Codex手動実行時に、DBから当日分を抽出して要約に使う導線

## Target Architecture
1. Collect Layer (Scheduled)
- topic別に情報取得
- dailyメモ生成
- market-signals更新

2. Normalize Layer (Scheduled)
- 欠損チェック
- entry-candidates生成
- DB投入

3. Present Layer (Manual Codex)
- DB当日分抽出
- Codexで「今日の情報」要約

## Windows Scheduler Strategy
- `make` は使わず `py` で直接スクリプト実行する
- nightly: `scripts/run_investment_automation.py --mode night`
- morning: `scripts/run_investment_automation.py --mode morning`
- brief: `scripts/data/build_today_brief_from_db.py`

## Current Implemented Scripts
- `scripts/run_investment_automation.py`
- `scripts/data/build_today_brief_from_db.py`
- `scripts/investment/signals/check_investment_signal_missing.py`
- `scripts/investment/signals/generate_entry_candidates.py`
- `scripts/data/init_investment_db.py`
- `scripts/data/ingest_investment_db.py`

## Next Tasks
- topic別の自動収集スクリプトを追加（RSS/API/公式サイト差分）
- 収集の失敗時リトライとログ整備
- daily summary の定型出力をPython生成できるようにする

## Operational Rule
- 収集と整形は自動
- 要約はCodex手動トリガー
- Codex実行時は DB Brief を優先入力とする
