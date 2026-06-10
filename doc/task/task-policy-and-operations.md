# Task運用方針（統合版）

## 1. タスク正本
- 各topicの `topics/<topic>/tasks.json` を正本とする。
- 長大化を避けるため、完了済み・過去検討分は `topics/<topic>/archive/` に退避する。
- 日常運用で参照するのは active タスク（`doing` と直近対応 `todo`）のみ。

## 2. investment-research 現行active
- invest_055: `inv-deep` のオンデマンド深掘り運用
- invest_056: backtest-expand週次運用（KPI達成まで継続）
- invest_058: ops_post障害分類と品質理由コード統合レビュー運用

## 3. 実装・運用の固定方針
- DB-first: 判定・連携の正本はDB。ファイル出力は監査/可視化用途。
- Stopしない運用: 品質劣化は `alert/warn` として扱い、処理異常（通信/DB/認証/実行不能）と分離。
- シナリオ運用: `trade` 不成立日でも `watch` 投稿は継続。
- サンプル運用: `sampleCount` 段階運用（0=watch, 1-2=paper_trade_only, >=3=become候補）。
- 夜間強化: outcomes補完・rule集計・週次レビューを定期実行し、母数を継続増強。

## 4. 用語の補足
- `become` は `trade` 候補を指す。
- `live` は `trade` 実績で、集計上は `trade` に含める。
- `watch` は監視継続で、`trade` の前段にある。

## 5. 変更管理ルール
- タスク追加時はまず `topics/<topic>/tasks.json` に登録。
- 完了時は同topicの `archive` へ定期退避（スナップショット保存）し、現行ファイルを肥大化させない。
- 方針変更は本ファイルに追記し、日付を明記する。

## 6. 2026-05-27 運用反映（投資収集/評価）
- 価格ソース方針:
  - 夜間の確定日足は JPX 相場表PDF（`stq_YYYYMMDD.pdf`）を主系列とし、`facts_price_daily(source_kind='jpx_stq_pdf')` に保存する。
  - `fill_market_outcomes.py` は `facts_price_daily` を優先参照し、不足時のみ Yahoo 日足へフォールバックする。
- バックフィル方針:
  - `run_recent_outcome_backfill` は 30/90/180 日窓を運用し、いずれも実取得あり（cache-only常用しない）。
  - `run_harvest_backfill.py` の日付ループでも JPX PDF 収集を実施し、遡及日付の補完を可能にする。
- JPX 月跨ぎ方針:
  - 対象日付の月差に応じて `index.html` / `00-archives-XX.html`（および `00-archive-XX.html`）を探索し、該当PDFを解決する。
- 昼評価（inv-noon）方針:
  - 場中は `collect_intraday_signal_snapshots.py`（Yahoo 15m）を主系列とし、TDnet/PDF は使わない。
  - `reevaluate_market_signals_noon.py` は gate と score を分離し、逆行強・欠損時は `hold_noon_recheck`、理由コードは `signals.payload_json.noonReeval` に記録する。
