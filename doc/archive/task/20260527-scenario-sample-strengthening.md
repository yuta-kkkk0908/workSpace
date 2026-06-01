# タスク分解: シナリオ母数強化 / 品質劣化時の継続運用（2026-05-27）

目的: 朝バッチを重くせずに `trade` 判定の再現性を上げる。  
方針: 「停止しない」「watchは必ず出す」「品質状態を明示する」。

## A. 先行改修（本日）

- [x] A-1: `signals` 時点で信用情報を保持（`credit_*` カラム）
- [x] A-2: シナリオ判定で `signals` の stale `auto_unknown` より当日 credit 行を優先
- [x] A-3: `post_scenarios_bot.py` を watch-only 日でも投稿継続
- [x] A-4: `inv-scenario` の fallback を 30日に拡大（朝の欠損耐性）
- [x] A-5: `rule_dashboard_rows` 欠損時は warn 継続（ジョブ停止しない）
- [x] A-6: `credit_auto_quality` 集計を `auto_%` 全体へ拡張
- [x] A-7: 楽天「信用取引規制銘柄一覧」を `auto_rakuten` として収集ラインに追加

## B. 次段（優先）

- [x] B-1: `rule_dashboard_rows` 不在時の暫定 `sampleCount` 推定（`backtest_outcomes` 直集計）
- [x] B-2: `pipeline_events` テーブル新設（slot/stage 単位の総合イベントログ + JSON payload）
- [x] B-3: `build_opening_scenarios` に品質状態出力（`planMode=trade/watch_only` の根拠を構造化）
- [x] B-4: `sampleCount` 段階運用
  - `0`: watch
  - `1-2`: paper-trade-only
  - `>=3`: trade候補

## C. 夜間強化（母数育成）

- [x] C-1: 夜間ジョブで `fill_market_outcomes -> analyze -> rule_check -> rule_dashboard` を固定連鎖
- [x] C-2: 直近30〜90日の再集計バックフィルを nightly で自動実施
- [x] C-3: `pending` 比率と有効母数を日次KPI化

## D. 受け入れ条件（Done）

- [x] D-1: 朝 `inv-scenario` が `exit 0` で継続（停止しない）※日次自動判定を実装
- [x] D-2: シナリオ0件が連続しない（最低 watch 投稿が継続）※日次自動判定を実装
- [x] D-3: `unknown_rate` が当面 30% 未満で安定 ※日次自動判定を実装
- [x] D-4: `rule_dashboard_rows` 欠損日でも品質理由が `planNotes` に明示される
- [x] D-5: 2週間で `sampleCount>=3` の銘柄比率が増加傾向 ※日次トレンド自動計測を実装

## E. 当日メモ

- 進捗（2026-05-27 追記）:
  - `scripts/data/init_investment_db.py` に `pipeline_events` 追加（index含む）
  - `scripts/utils/pipeline_events.py` を新設し、共通DBイベント書き込みを実装
  - `scripts/run_ops_scheduler.py` で slot開始/終了 + 各サブコマンド結果を `pipeline_events` に記録
  - `scripts/investment/analysis/report_credit_auto_quality.py` と `report_rule_thin_diagnostics.py` からも `pipeline_events` へ記録
  - `scripts/investment/signals/build_opening_scenarios.py` に `qualityState`（status/degradedReasons/accepted/rejected内訳）を追加し、同内容を `pipeline_events(stage=build_opening_scenarios)` に記録
  - `sampleCount` 段階運用を実装（`0/watch`, `1-2/paper_trade_only`, `>=3/trade`）
  - `scripts/notify/post_scenarios_bot.py` で `paper_trade_only` を `PAPER` 表示・投稿対象として扱い、auto paper-trade登録は `mode=watch` で記録
  - `scripts/investment/backtest/register_paper_trades.py --tier paper_trade_only` を追加
  - `scripts/investment/analysis/check_inv_scenario_acceptance.py` を追加し、`D-1..D-3` を日次チェック（MD/JSON出力 + `pipeline_events` 記録）
  - `run_ops_scheduler --slot inv-scenario` に受け入れチェック呼び出しを追加
  - `rule_dashboard_rows` 欠損時の `planNotes` を常時出力に修正（sample hint 有無どちらでも明示）
  - `scripts/investment/analysis/report_samplecount_trade_trend.py` を追加し、`sampleCount>=3` 比率の14日トレンドを日次計測（MD/JSON出力 + `pipeline_events` 記録）
  - `run_ops_scheduler --slot inv-scenario` にトレンド計測呼び出しを追加
  - `scripts/investment/analysis/report_sample_health_kpi.py` を追加し、`pendingAllRatio` と `effectiveSampleRatio` を日次計測（MD/JSON出力 + `pipeline_events` 記録）
  - `run_ops_scheduler --slot inv-scenario` に sample health KPI 呼び出しを追加
  - `scripts/investment/backtest/backfill_recent_outcomes_window.py` を追加し、nightlyで直近30日（毎日）/90日（月曜）を自動バックフィル
  - `run_ops_scheduler --slot night` に outcomes バックフィル呼び出しを追加
  - `run_ops_scheduler --slot inv-scenario --date 2026-05-27 --backtest` 実行で記録確認済み

- 信用取得ソース:
  - 楽天規制一覧は「掲載=規制あり」「非掲載=規制なし」の解釈で運用
  - source_kind 優先は `manual > auto_rakuten > auto_sbi`
- 現状ボトルネック:
  - `trade` 昇格阻害の主因は `sampleCount<1`（信用 unknown は副次）

## F. 次フェーズ（paper_trade_only 品質担保）

- [x] E-1: `paper_trade_only` 専用KPI（日次）
  - 勝率、期待値、最大DD、件数不足率を `mode=watch` 集計で算出
  - `topics/investment-research/inbox/{date}-paper-trade-only-kpi.md/json` を出力
- [x] E-2: `paper_trade_only -> trade` 昇格基準の実装
  - 直近N件の成績条件（勝率/期待値/ドローダウン）を満たした銘柄のみ `trade` 候補へ昇格
  - 昇格/非昇格理由を `pipeline_events` に記録
- [x] E-3: 失敗要因の自動集計と閾値見直しループ
  - 信用可否・流動性・時間帯・イベント種別ごとの負け要因を日次集計
  - 週次で `paper_trade_only` 閾値（`sampleCount`, `minScore`, `minRuleHits`）の見直し候補を自動出力

## G. タスク棚卸（2026-05-27）

- `topics/investment-research/tasks.json` と本ドキュメントの整合を更新。
- `done` へ更新:
  - `invest_041` 週次ルール再現性自動集計
  - `invest_048` T+1/T+5/T+20未更新シグナル自動抽出
  - `invest_054` long/short候補の週間パフォーマンス集計
  - `invest_057` paper_trade_only失敗要因集計 + 週次見直しループ
- `doing` へ更新:
  - `invest_056` backtest-expand週次運用（実行自動化済み、KPI評価継続）

## H. invest_056 完了判定（2026-05-27）

- 対象タスク: `invest_056` investment-backtest-expandを週次で実行し、ルール再現性母数を増やす
- 現在ステータス: `doing`（自動実行は実装済み、KPI達成待ち）

- Done条件（2週間ローリングで判定）:
  - 実行継続: night/eveningで `fill_market_outcomes` / rule系集計 / 30日+90日backfill が継続成功
  - 母数拡張: `rule-history` の `hypothesis_only` 比率が逓減傾向
  - 品質改善: `weekly-tuning-review` の `credit_unknown_ratio_pct` が 30%未満で安定
  - 運用反映: `non_trade_ratio_pct` が低下傾向（watch偏重の緩和）

- 2026-05-27時点の観測:
  - 自動実行: 実装済み（scheduler接続済み）
  - `credit_unknown_ratio_pct`: 98.698%（未達）
  - `non_trade_ratio_pct`: 73.684%（改善余地大）
  - 判定: Done未達のため `doing` 継続

## I. 異常系と品質警告の分離ポリシー（2026-05-27）

- 目的: ジョブ失敗（exit非0）を「処理異常」に限定し、品質劣化は `QUALITY_WARN` / `status=alert` として別管理する。

- 処理異常（exit非0）:
  - 通信失敗（source/API/Discord）
  - DB接続/SQL実行失敗
  - 認証/認可失敗
  - JSON解析・必須入力欠落などで処理継続不能

- 品質警告（exit=0 + alert）:
  - ソース薄く signal が不足
  - 当日新規材料不足
  - 信用情報不足
  - シナリオ昇格不可（watch偏重）
  - noon snapshot カバレッジ不足

- 実装反映:
  - `check_signal_quality.py` は `ALERT` でも `exit 0`。`pipeline_events(status=alert)` と `reasonCodes` を記録。
  - `post_signal_discord.ps1` は `DISCORD_SIGNAL_QUALITY_FAIL_THRESHOLD` で品質警告の失敗化を制御（既定0）。
  - `post_signal_quality_alert.ps1` は品質判定結果の通知は警告扱いだが、判定処理/通知処理の実行失敗は非0で返す。
  - `scripts/ops/task_runner_common.ps1` に post-step 異常分類（`discord_delivery/source_fetch/db_error/auth_error/process_error`）を追加。
  - `do_inv_morning/noon/evening/scenario_and_post.ps1` は post-stepごとの結果を `pipeline_events(pipeline=ops_post)` へ記録。
  - `report_weekly_tuning_review.py` は `check_signal_quality.py status=alert` の `qualityReasonCodes` を週次集計して `quality_reason_counts` を出力。
