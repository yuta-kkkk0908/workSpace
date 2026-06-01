# 2026-05-29 Scenario Quality / Tracking Implementation Review

## 目的
- 現在の実装が「entry実績中心」ではなく「予測品質中心」で動いているかを確認する
- `promoted / rejected_weak / rejected_other` の追跡設計と、通知の意思決定ロジックを明文化する

## 結論（先に要点）
- 主評価軸は `entry conversion` ではなく、`T+5/T+20` の勝率・サンプル数で見るべき
- 実装はこの方向へ寄せており、`rejected_weak` を分離追跡する経路を追加済み
- ただし、日次判断はまだ「運用通知」と「品質KPI」が分散しているため、レビュー運用が必要

## 実装スコープ（2026-05-29時点）

## 処理全体フロー（シグナル -> シナリオ -> バックテスト）
1. シグナル生成
2. エントリー候補化
3. シナリオ昇格判定（accepted/rejected）
4. 投稿・paper登録
5. バックテスト結果の更新
6. KPI/アラートで次アクション決定

---

## 1) シグナル生成でやっていること
- 主スクリプト:
  - `scripts/investment/signals/build_market_signals_from_batches.py`
  - `scripts/investment/signals/generate_entry_candidates.py`
- 入力:
  - TDNET/Kabutan等の収集結果
  - 価格/信用などDB情報
- 出力:
  - `signals` テーブル
  - `entry_candidates` テーブル
- 重要点:
  - 最近の上限は scheduler で拡張（`max-signals=12`, `max-long=6`, `max-short=6`）
  - ここは「候補を作る段」で、まだシナリオ採用確定ではない

## 2) シナリオ昇格判定でやっていること
- 主スクリプト:
  - `scripts/investment/signals/build_opening_scenarios.py`
- 入力:
  - `entry_candidates`
  - ルール再現性/勝率ヒント（DB）
  - 信用可否情報
- 判定:
  - `accepted`（シナリオ採用）
  - `rejected`（非採用）
- 非採用理由例:
  - `ruleHits<...`
  - `score<...`
  - `winRate<...`
  - `credit_unavailable...`
- 出力:
  - `opening_scenarios`（`source_kind='scenario'` or `'rejected'`）
  - `scenario_gate_diagnostics`（理由・判定根拠）
- 補足:
  - `--auto-relax-gate` は「当日運転の救済」用途
  - 恒久閾値の変更は別途レビュー判断
  - 2026-05-29時点で `technicalTag` を付与し、`scenarioScore` に小さな補助加点（最大+3）を追加

## 3) 投稿・paper登録でやっていること
- 主スクリプト:
  - `scripts/notify/post_scenarios_bot.py`
- 投稿:
  - scenarioをDiscord投稿
  - 同一条件は既存スレッド再利用（期間内）
- paper登録:
  - `trade / paper_trade_only / watch` を `paper_trades` へ自動upsert
  - watchは `mode=watch`
- 補足:
  - 投稿失敗は配信失敗
  - 予測品質の判定は別（backtest/KPI）

## 4) バックテストでやっていること
- 主スクリプト:
  - `scripts/investment/backtest/fill_market_outcomes.py`
  - `scripts/investment/backtest/backfill_recent_outcomes_window.py`
  - `scripts/investment/backtest/register_paper_trades.py`
- 何を計算するか:
  - `T+1/T+5/T+20` で win/lose/pending を付与
  - 成績を `backtest_outcomes` に蓄積
- コホート:
  - `promoted`（accepted）
  - `rejected_weak`（品質理由で非採用）
  - `rejected_other`（品質理由以外）
- 重要点:
  - 「entryしたかどうか」は主評価ではない
  - 主評価は各コホートの将来成績（勝率/リターン）

## 5) KPI/アラートでの意思決定
- 主スクリプト:
  - `scripts/investment/analysis/report_decision_support_kpi.py`
  - `scripts/notify/post_signal_quality_alert.ps1`
- 何を比較するか:
  - `promoted vs rejected_weak` の T+5
  - `7d/30d/90d` の窓で差分確認
- Decision Card:
  - `KEEP / RELAX / TIGHTEN`
  - `n<20` は変更しない（ガード）

---

### 1) シナリオ投稿とスレッド再利用
- 対象: `scripts/notify/post_scenarios_bot.py`
- 追加仕様:
  - `--thread-reuse-days`（既定 7日）
  - 以下一致時は既存スレッド再利用
    - `ticker`
    - `direction`
    - `scenarioTier`
    - `watch/paper` の場合は `watchLadder` も一致
  - 期間外または不一致は新規スレッド作成
- 2026-05-29障害修正:
  - DB再接続時の `row_factory` 未設定を修正（tuple参照エラー対策）
  - Discord投稿運用を Python 優先に統一（Webhook 403 時は `User-Agent` 明示で再送）

### 2) watch の paper 自動登録
- 対象: `scripts/notify/post_scenarios_bot.py`
- 仕様:
  - `trade / paper_trade_only / watch` を `paper_trades` へ自動 `upsert`
  - `watch` は `mode=watch` で登録
  - `scenarioIndex` 欠損時は投稿順で補完

### 3) 弱い非昇格群の分離追跡
- 対象: `scripts/investment/backtest/register_paper_trades.py`
- 追加仕様:
  - `--rejected-policy`:
    - `all`
    - `weak_only`
    - `other_only`
  - `scenario_gate_diagnostics.reject_reasons_json` を参照して分類
    - `rejected_weak`: `ruleHits<`, `score<`, `winRate<`, `RULE_THIN_*`
    - `rejected_other`: 上記以外
  - `paper_trades.source_path` 末尾に `#cohort=...` を付与

### 4) scheduler 呼び出しの変更
- 対象: `scripts/run_ops_scheduler.py`
- 変更:
  - `inv-scenario` 内 `register_paper_trades.py` を `--rejected-policy weak_only` で実行
  - `--max-trades 60` に拡張
  - `build_market_signals_from_batches.py` 上限を `6 -> 12` 系に拡張
  - `build_opening_scenarios.py` に `--max-candidates 12` を明示

### 5) Decision Support KPI のコホート化
- 対象: `scripts/investment/analysis/report_decision_support_kpi.py`
- 追加仕様:
  - 従来KPI（pass/hold）は維持
  - 新規にコホートKPIを追加
    - `promoted`
    - `rejected_weak`
  - `cohortWindows` として `7d/30d/90d` をJSON出力
  - `technicalTag` 別の `T+5` 集計を追加（`promoted/rejected_weak` を比較）

### 6) Alert を Decision Card 化
- 対象: `scripts/notify/post_signal_quality_alert.ps1`
- 追加仕様:
  - 通知に `decision: KEEP/RELAX/TIGHTEN` を明示
  - `decision-support-kpi.json` から `promoted vs rejected_weak` 差分を参照
  - 判定ガード:
    - `min(n) < 20` は閾値変更しない
  - 根拠行:
    - `evidence(T+5)`
    - `evidence(7d/30d/90d)`
  - `reasonCodes` ごとのアクション文を通知に添付

## 現在の評価軸（整理）
- 主KPI（品質）:
  - `T+1/T+5/T+20` 勝率
  - 平均リターン
  - `n`（サンプル数）
  - 比較軸: `promoted vs rejected_weak`（必要に応じて `rejected_other`）
- 副KPI（運用受容）:
  - `entries/posts`（entry conversion）
- 方針:
  - 現フェーズは主KPIを優先し、entry実績は副次指標として扱う

## レビュー観点（チェックリスト）
- [ ] `promoted` と `rejected_weak` が混在せず集計されている
- [ ] `rejected_weak` 判定条件（reason code）が意図通り
- [ ] `cohortWindows(7d/30d/90d)` が毎日生成される
- [ ] Alert の `decision` が根拠行と整合する
- [ ] `n<20` のとき閾値変更提案を抑制できている
- [ ] シナリオ投稿失敗時に再送/再実行手順が明確

## 既知リスク
- `rejected_data_quality` を専用コホートとして明示分離する実装は未着手
- 通知と分析レポートの二重経路により、判断が分散しやすい
- 日次自動判定は導入済みだが、週次レビューでの人手監査は引き続き必要

## 次アクション（提案）
1. `rejected_data_quality` コホートを追加し、`rejected_weak` と分離比較する
2. 毎朝の運用向けに「1画面サマリ（KPI + decision + actions + technicalTag上位）」を単一ファイルで生成する
3. 7営業日で `opening_scenarios/day`, `0件日率`, `cohort T+5 gap`, `technicalTag別n` の改善有無を判定する

## 実行記録（2026-05-29）
- 実行:
  - `python scripts/investment/backtest/register_paper_trades.py --date 2026-05-29 --mode watch --tier all --rejected-policy weak_only --max-trades 60 --fallback-days 30`
  - `python scripts/investment/backtest/register_paper_trades.py --date 2026-05-29 --mode watch --tier all --rejected-policy data_quality_only --max-trades 60 --fallback-days 30`
  - `python scripts/investment/analysis/report_decision_support_kpi.py --date 2026-05-29 --window-days 30`
- 出力確認:
  - `topics/investment-research/inbox/2026-05-29-decision-support-kpi.md` に `rejected_data_quality` 行を確認
  - 同 Markdown に `Technical Tags (T+5)` セクションを確認
  - `topics/investment-research/inbox/2026-05-29-decision-support-kpi.json` に `technical_t5` / `cohortWindows` を確認
  - `python scripts/investment/analysis/report_scenario_tracking_card.py --date 2026-05-29 --window-days 7` を実行し、1画面サマリ（tracking card）を生成
