# タスク: 売買判断支援システムへの実装準備（自動売買なし）

## 目的
既存の `investment` パイプラインを土台に、**人間の売買判断を支援する品質**を段階的に上げる。  
対象は「提案・評価・観測」の自動化であり、注文自動実行は含めない。

## スコープ
- 対象: `scripts/investment/signals/*`, `scripts/investment/analysis/*`, `scripts/run_ops_scheduler.py`
- 対象DB: `data/investment.db`
- 非対象: 自動発注連携、ブローカーAPI実行

## タスク一覧

### ds_001: 判定理由の固定出力を標準化
- status: done (2026-05-28)
- priority: high
- 実装先:
  - `scripts/investment/signals/build_opening_scenarios.py`
  - `scenario_gate_diagnostics.payload_json`
- 内容:
  - `why_pass`, `why_hold`, `why_reject` を定義済みキーで保存
  - スコア内訳（`scoreBreakdown`）と整合する説明文を保存
- 受け入れ条件:
  - `opening_scenarios` 採用/保留/除外すべてで理由キーが欠落しない

### ds_002: 判断精度KPIレポートを追加
- status: done (2026-05-28)
- priority: high
- 実装先:
  - `scripts/investment/analysis/report_decision_support_kpi.py`（新規）
  - `scripts/run_ops_scheduler.py` (`inv-scenario` slot)
- 内容:
  - `scenario_gate_diagnostics` と `backtest_outcomes` を結合
  - `T+5/T+20` 観点で pass/hold 提案の勝率・失敗率を日次集計
- 受け入れ条件:
  - `topics/investment-research/inbox/*-decision-support-kpi.md` が日次生成される

### ds_003: 執行しやすさスコアを導入
- status: done (2026-05-28)
- priority: high
- 実装先:
  - `scripts/investment/signals/build_opening_scenarios.py`
  - 参照: `board_snapshots`, `market_signal_snapshots`
- 内容:
  - `execution_feasibility_score` を算出（板/出来高/ギャップ/スプレッド近似）
  - シナリオ本文と payload に追加
- 受け入れ条件:
  - 全シナリオで `executionFeasibilityScore` が出力される（欠損時は `unknown`）

### ds_004: 昇格は「提案のみ」を明示化
- status: done (2026-05-28)
- priority: medium
- 実装先:
  - `scripts/notify/post_scenarios_bot.py`
  - `scripts/investment/analysis/report_samplecount_trade_trend.py`
- 内容:
  - `watch/paper/trade` は自動発注ではなく「判断提案」であることを明示
  - `watchLadder` 理由を文面出力
- 受け入れ条件:
  - 投稿文面に提案である旨と昇格根拠が表示される

### ds_005: 変更差分の自動評価
- status: done (2026-05-28)
- priority: medium
- 実装先:
  - `scripts/investment/analysis/report_phase_a_score_sensitivity.py`（拡張）
  - `scripts/investment/analysis/report_decision_support_diff.py`（新規）
- 内容:
  - 前回設定との差分（勝率、DD近似、採用件数）を比較
  - 改悪検知時に warning を出す
- 受け入れ条件:
  - 前日比の改善/悪化が自動で判定される

## 実装順（推奨）
1. ds_001
2. ds_002
3. ds_003
4. ds_004
5. ds_005

## 準備メモ
- 既存資産の活用:
  - 判定土台: `build_opening_scenarios.py`
  - 監査土台: `scenario_gate_diagnostics`
  - 感度分析土台: `report_phase_a_score_sensitivity.py`
- 注意:
  - 売買助言に見える文面を避け、「提案/観測/検証」を明示する
