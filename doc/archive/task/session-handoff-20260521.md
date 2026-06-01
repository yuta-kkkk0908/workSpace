# セッション引き継ぎメモ（2026-05-21）

## 合意（運用）
- 中断前提で、毎回「解釈・同意・実装・次回再開手順」を作業ドキュメントへ残す。
- 主導権をユーザーへ返す前に記録を先に固定する。

## 収集データ分析の現在地（watch→trade）
- 直近14日: `signals=103`, `entry_candidates=28`, `execution_plan=43`, `paper_trades=30`
- 主ボトルネック: `paper_trades.mode='watch'` 実績が0で、昇格分析 (`analyze_watch_promotion.py`) の母数がない。
- 連携課題: `execution_plan -> paper_trades` 同日紐付けが 11/43 で低い。
- 品質課題: `execution_plan` の `rank/ev/rr` 欠損が多い。

## 通知基盤で今回実装した解釈
- 生成停止ではなく「送信段の不達」が主因。
- 対策は個別修正ではなく送信処理の共通化。

## 実装済み（通知）
- 共通化:
  - `scripts/notify/discord_common.ps1`
  - `scripts/notify/post_discord_message.ps1`
- ラッパー化:
  - `scripts/notify/post_generic_discord.ps1`
  - `scripts/notify/post_signal_discord.ps1`
  - `scripts/notify/post_scenario_discord.ps1`
  - `scripts/notify/post_paper_stats_discord.ps1`
- pending再送:
  - `scripts/notify/resend_pending_discord.ps1`
- 後続タスク起動時に通知前で pending 再送を追加:
  - `scripts/ops/run_night_and_post_generic.ps1`
  - `scripts/ops/run_inv_morning_and_post.ps1`
  - `scripts/ops/run_inv_noon_and_post.ps1`
  - `scripts/ops/run_inv_evening_and_post.ps1`
  - `scripts/ops/run_inv_scenario_and_post.ps1`

## 次回の再開順
1. `paper_trades.mode` 分布と watch件数を確認
2. watch実績の記録経路を実装
3. `execution_plan -> paper_trades` 未連携理由を分類
4. 14日/30営業日のファネル再集計を更新

## 追加タスク（2026-05-21）: 価格テクニカルシグナル拡張
- [x] T-1: MA反発 / ボリンジャー追従 / ボリンジャー反発 / 3本陽線系シグナルの設計合意
- [x] T-2: `facts_price_daily` 由来で日次技術シグナルを生成するスクリプト追加
- [x] T-3: スケジューラフローへ接続（entry候補生成前に実行）
- [ ] T-4: 30営業日で技術シグナル別の T+1/T+5 事後成績を検証（採用閾値調整）

### 実装メモ
- 追加: `scripts/investment/signals/generate_technical_signals.py`
- 追加シグナル種別:
  - `technical_ma_rebound`
  - `technical_bb_follow_up`
  - `technical_bb_rebound_up`
  - `technical_three_white_soldiers`
  - `technical_three_black_rebound_watch`
- 接続: `scripts/run_ops_scheduler.py`
  - `generate_entry_candidates.py` の前に `generate_technical_signals.py --date <d>` を挿入

## 追加進捗（2026-05-21 後半）

### A. 技術シグナル検証（30営業日）
- 実装:
  - `scripts/investment/analysis/analyze_technical_signal_performance.py`
  - `scripts/investment/signals/backfill_technical_signals.py`
- 実行:
  - 直近40営業日をバックフィル後、30営業日評価を実施
- 結果（2026-05-21時点）:
  - total_samples: 778
  - `technical_three_white_soldiers`: T+5 wr=43.7%, avg=0.668%
  - `technical_ma_rebound`: T+5 wr=41.8%, avg=0.7853%
  - `technical_bb_follow_up`: T+5 wr=41.8%, avg=-1.6225%
  - `technical_bb_rebound_up`: T+5 wr=46.9%, avg=-1.9746%
- 解釈:
  - 現閾値では昇格候補なし（全て `watch_more`）。
  - ただし `three_white_soldiers` / `ma_rebound` は平均リターン正で、条件絞り込み余地あり。

### B. watch→trade ボトルネック解消（登録経路）
- 問題:
  - `opening_scenarios` の watch 行が `source_kind='rejected'` で、
    `register_paper_trades.py` の `source_kind='scenario'` 条件に弾かれていた。
- 修正:
  - `register_paper_trades.py`
    - `source_kind IN ('scenario','rejected')` に拡張
    - `--fallback-days` を追加
    - `--mode watch --tier watch` 登録を正式対応
- 結果:
  - `paper_trades.mode='watch'` が 1件生成されることを確認。

### C. スケジューラ接続
- `scripts/run_ops_scheduler.py`
  - `inv-evening`: 技術シグナル性能分析を日次実行
  - `inv-scenario`: watchモード paper登録を日次実行（fallback 3日）

### D. 次アクション（優先順）
1. watch件数を継続蓄積（最低 n>=20）して昇格判定を再評価
2. `technical_bb_follow_up` / `bb_rebound_up` の逆風条件を絞り込む（地合い/出来高）
3. `ma_rebound` / `three_white_soldiers` を流動性条件付きで再検証

### 追加進捗（2026-05-21 夕方）
- watch登録母数は 0 -> 2 へ増加（2026-05-20, 2026-05-21）。
- 依然として昇格判定母数不足のため、`inv-scenario` の watch登録を `tier=all`（shadow含む）へ拡張。
- これにより、watch-only停滞時でも日次で昇格評価用サンプルを蓄積可能。

### 追加進捗（2026-05-21 夜）: watch成果未充填ボトルネックの解消
- 症状:
  - `paper_trades.mode='watch'` は 234 行あるのに、`t5_return_pct` が 0 行で昇格判定不能。
- 原因:
  - `fill_paper_trade_outcomes.py` の `--mode` が `watch` 非対応だった。
  - 価格取得が Yahoo API 依存で、watch母集団の多くが未更新のまま残っていた。
- 実装:
  - `scripts/investment/backtest/fill_paper_trade_outcomes.py`
    - `--mode` に `watch` を追加（choices: `backtest|live|watch|all`）。
    - DB一次取得を追加: `facts_price_daily` から日足closeを先に読む。
    - DBで取れない場合のみ従来の Yahoo 取得にフォールバック。
- 実行結果:
  - `python scripts/investment/backtest/fill_paper_trade_outcomes.py --mode watch --as-of 2026-05-21`
  - 更新件数: 232
  - watch集計:
    - total=234
    - T+1あり=212
    - T+5あり=159
    - T+20あり=21
    - status: `closed_t20_ready=21`, `open_partial=191`, `open_pending_outcome=22`
- 昇格分析再実行:
  - `python scripts/investment/backtest/analyze_watch_promotion.py --out-date 2026-05-21`
  - 出力: `topics/investment-research/inbox/2026-05-21-watch-promotion-candidates.md`
  - 結果: promotion_candidates=5 / near_candidates=30

### 解釈メモ（同意処理）
- 「watch→trade判定の母数確保」を優先し、外部API可用性に依存しないよう `facts_price_daily` を正とする方針に寄せた。
- 昇格候補は暫定閾値（n>=3, T+5 win>=55%, avgRet>=0.2%）での機械抽出。運用反映は別途レビュー前提。

### 追加進捗（2026-05-21 深夜）: 昇格分析へ流動性フィルタ追加
- 変更: `scripts/investment/backtest/analyze_watch_promotion.py`
  - 新オプション:
    - `--min-avg-turnover-mil`（昇格に必要な平均売買代金, 百万円）
    - `--turnover-lookback-days`（平均計算の遡り営業日、既定20）
  - 算出:
    - `facts_price_daily` から `close * volume` を直近N営業日で平均し、`avg_turnover_mil` を各銘柄評価に付与
  - 判定:
    - 既存閾値（samples/wr/avgRet）に加えて流動性閾値も満たした場合のみ昇格候補
  - 出力:
    - 候補/nearに `avg_turnover` を明記

- 比較実行:
  - base: `--min-avg-turnover-mil 0`
  - liq500: `--min-avg-turnover-mil 500`
- 結果:
  - どちらも `promotion_candidates=5`, `near_candidates=30`（今回の上位候補は既に流動性基準を満たしていた）
  - ただし near 側では、流動性不足理由が明示されるようになり、除外根拠が可視化された。

### 追加進捗（2026-05-21 深夜2）: 流動性閾値の感度分析
- 実行:
  - `--min-avg-turnover-mil` を `0/300/500/700/1000` で比較
- 結果:
  - liq>=0: candidates=5
  - liq>=300: candidates=5
  - liq>=500: candidates=5
  - liq>=700: candidates=5
  - liq>=1000: candidates=4（`6617` が除外）
- 解釈:
  - 現在の昇格候補上位は総じて流動性が高く、閾値700までは影響なし。
  - 1000で初めて候補削減が発生するため、運用の初期推奨は `700`（過度に候補を落とさず安全側）とする。

### 追加進捗（2026-05-21 深夜3）: スケジューラへ流動性閾値を反映
- 変更: `scripts/run_ops_scheduler.py`
  - 定数追加: `WATCH_PROMOTION_MIN_AVG_TURNOVER_MIL = "700"`
  - `inv-evening` の `analyze_watch_promotion.py` 呼び出しへ
    - `--min-avg-turnover-mil 700` を追加
- 反映意図:
  - 手動実行時の分析条件と定期実行条件のズレをなくし、
    watch→trade判定の運用閾値を固定化する。

### 追加進捗（2026-05-21 深夜4）: 定期実行でwatch結果を自動充填
- 変更: `scripts/run_ops_scheduler.py` (`inv-evening`)
  - `analyze_watch_promotion.py` の前に以下を追加:
    - `fill_paper_trade_outcomes.py --mode watch --as-of <date>`
- 目的:
  - 昇格分析が stale な watch 行（T+5未充填）を参照しないようにし、
    手動メンテなしで毎日母数を更新する。
- 検証:
  - `python -m py_compile` で関連3ファイルの構文OK。

### 追加進捗（2026-05-21 通知文面修正）
- 変更1: 汎用トピック通知を圧縮表示
  - `scripts/notify/render_generic_topics_discord_message.py`
  - 各トピックを「要約行（最大3）+ 出典1本」に変更
  - `掲載時刻` などノイズ行を除外
- 変更2: シグナル速報の unknown 表示を整理
  - `scripts/notify/render_market_signals_discord_message.py`
  - `company=不明/unknown` は銘柄名表示から除外
  - `signal_type=unknown/空` は `判定情報不足（分類未設定）` へ統一
- 変更3: シナリオ0件時に理由を追記
  - `scripts/notify/render_opening_scenarios_discord_message.py`
  - 0件時に `候補 / trade採用 / watch判定 / 実行計画` の内訳を出力
- 変更4: Signal Quality Alert の重複警告を統合
  - `scripts/investment/signals/check_signal_quality.py`
  - `trade=0` と `watchShare高` を `シナリオ構成偏り` 1行に統合

- 生成確認（2026-05-21 再レンダリング）
  - `prompts/generic-topics-discord-message.txt`
  - `prompts/market-signals-discord-message.txt`
  - `prompts/opening-scenarios-discord-message.txt`
  - `prompts/signal-quality-alert.txt`

### 追加メモ（2026-05-21 夜）: inv-evening手動実行と通知見え方
- ユーザー操作: タスクスケジューラーから `AIOS-Inv-Evening` を手動実行。
- 確認結果:
  - `logs/task-scheduler.log` 上は `START -> OK` で完了。
  - 同時刻で `discord-signal.log / discord-paper-stats.log / discord-signal-quality-alert.log` が更新。
- 解釈:
  - 通知処理自体は実行されている。
  - 「流れていないように見える」主因は、`SKIP(unchanged)` や同内容判定、または到達遅延の可能性。
- 対応方針:
  - ひとまず現状運用で継続。
  - 再発時は該当時刻の3ログを抜粋して `posted / skip / pending` を即確認する。

### 追加進捗（2026-05-21 深夜）: unchanged時の通知追加
- 変更: `scripts/notify/post_discord_message.ps1`
  - 新オプション `-NotifyOnUnchanged` を追加。
  - `SkipIfUnchanged` でスキップ判定になった際、Discordへ「更新なし（unchanged）」を1件送る動作を追加。
  - `-AsEmbed` 有効時は embed で、通常時は text で通知。
- 反映先ラッパー:
  - `scripts/notify/post_generic_discord.ps1`
  - `scripts/notify/post_signal_discord.ps1`
  - `scripts/notify/post_paper_stats_discord.ps1`

### 追加進捗（2026-05-21 深夜・分析再開）
- watch成果を最新化:
  - `fill_paper_trade_outcomes.py --mode watch --as-of 2026-05-21` 実行（updated=213）
  - watch集計: total=234 / T+1=213 / T+5=159 / T+20=21
- 昇格分析（流動性閾値700）:
  - `analyze_watch_promotion.py --out-date 2026-05-21 --ladder --min-avg-turnover-mil 700`
  - watch_rows=234, promotion_candidates=5
  - ladder: early=5 / balanced=5 / strict=1
- 技術シグナル30営業日評価:
  - samples=778
  - three_white_soldiers: n=311, T+5 wr=43.7%, avg=0.668%（watch_more）
  - ma_rebound: n=237, T+5 wr=41.8%, avg=0.7853%（watch_more）
  - bb_follow_up: n=134, T+5 wr=41.8%, avg=-1.6225%（watch_more）
  - bb_rebound_up: n=96, T+5 wr=46.9%, avg=-1.9746%（watch_more）
- ボトルネック再計測（直近14日 2026-05-08..2026-05-21）:
  - execution_plan total=43
  - plan->paper_trades 紐付=23（link_rate=53.5%）
  - execution_plan 欠損: rank=95.3%, ev=100.0%, rr=100.0%
- 解釈:
  - watch母数は解消済み。
  - 次の主ボトルネックは `execution_plan` の評価指標欠損（rank/ev/rr）で、
    ここが埋まらない限り trade 側の再現性評価が鈍い。

### 追加進捗（2026-05-21 深夜・execution_plan 指標接続）
- 変更1: `build_execution_plan.py`
  - `fallback-days` を実装（`sourceDate=max(scenario_date)` を参照）
  - `rank` を `signals.long_rank/short_rank` から方向別に反映
  - `estimated_winrate_text` から勝率%の補完パースを追加
  - `entry` 欠損時に `facts_price_daily.close` を参照し、`tp/sl` 欠損時は簡易bracketで補完
- 変更2: 新規 `scripts/investment/signals/fill_execution_plan_metrics.py`
  - 既存 `execution_plan` に対して後埋め補完を実施
  - 補完対象: `rank, entry, tp, sl, rr, ev`
  - rank: `entry_candidates -> signals` の順で補完
  - 価格: `facts_price_daily.close` 補完
  - rr/ev: 価格と勝率情報がある範囲で再計算
- 変更3: `run_ops_scheduler.py`
  - `inv-scenario` で `build_execution_plan.py` の直後に
    `fill_execution_plan_metrics.py --start-date d --end-date d` を実行

- 実測（直近14日 2026-05-08..2026-05-21）
  - 補完前: rank 2/43, rr 0/43, ev 0/43
  - 補完後: rank 42/43 (97.7%), rr 8/43 (18.6%), ev 0/43
- 解釈:
  - rank欠損は実質解消。
  - rr は価格欠損が残る銘柄を中心に未充填。
  - ev は勝率情報が不足（`estimated_winrate_value/text` 不足）で未充填が残る。

### 追加進捗（2026-05-21 深夜・EV補完強化）
- 変更: `scripts/investment/signals/fill_execution_plan_metrics.py`
  - 勝率欠損時のフォールバックを追加:
    1) `opening_scenarios.estimated_winrate_value/text`
    2) `rule_dashboard_rows` の side別直近 `t5`（無ければ`t1`）の wr
    3) rankベース既定値（A+/A/B+/B/C/other）
  - これにより、価格が埋まる行では `ev` も算出可能に。
- 再実行結果（2026-05-08..2026-05-21）:
  - total=43
  - rank filled: 42 (97.7%)
  - rr filled: 8 (18.6%)
  - ev filled: 8 (18.6%)  ※ 0 -> 8 へ改善
- 残課題:
  - rr/ev 未充填の主因は `entry/tp/sl` 価格欠損（facts_price_dailyに該当closeが無い銘柄）。

### 追加進捗（2026-05-21 深夜・価格フォールバック追加）
- 変更: `fill_execution_plan_metrics.py`
  - `entry` 欠損時、当日closeが無ければ `plan_date` より前の直近closeを補完
- 再実行結果（2026-05-08..2026-05-21）
  - total=43
  - rank filled: 42 (97.7%)
  - entry filled: 23 (53.5%)
  - rr filled: 23 (53.5%)
  - ev filled: 23 (53.5%)
- 解釈:
  - 価格フォールバックで rr/ev 充填率が 18.6% -> 53.5% に改善。
  - 残る未充填は、ticker自体の価格系列が欠ける銘柄が中心。

### 追加進捗（2026-05-21 深夜・母数不足対策）
- 実施:
  - `register_watch_trades_from_signals.py --start-date 2025-12-01 --end-date 2026-03-31 --max-per-day 20`
  - 追加登録: 120件（technical_daily shadow watch）
  - `fill_paper_trade_outcomes.py --mode watch --as-of 2026-05-21` で outcomes更新: 370件
- watch母数（更新後）:
  - total=747
  - T+1=734
  - T+5=651
  - T+20=377
- 再分析:
  - `analyze_watch_promotion.py --min-avg-turnover-mil 700 --ladder`
  - promotion_candidates=14
  - ladder: early=27 / balanced=27 / strict=9
- 解釈:
  - 「母数不足」は実質解消。
  - 次段階は候補の過密化を避けるため、候補の昇格上限（日次本数）と sector分散ルールを追加するフェーズ。

### 追加進捗（2026-05-22）: 母数強化・DB中心運用
- 合意の再確認:
  - 運用フローの入力/判断はDBを正とし、ファイル出力は監査ログ用途に限定する。
  - 「結果ファイルを読んで次処理する」依存は段階的に解消する。

- 実装/反映:
  - `scripts/investment/analysis/report_signal_type_coverage.py`
    - `signal_type_coverage_rows` へDB保存を標準化（`--no-write-files` 既定運用）。
  - `scripts/investment/collect/run_harvest_backfill.py`
    - 不足シグナル判定を `signal_type_coverage_rows` 優先で参照し、収集ブーストを自動化。
  - `scripts/investment/collect/collect_tdnet_disclosures.py`
    - 収集時にTDNETタイトル分類を適用。
    - 当日収集0件でも対象日の既存行を再分類する `recategorized` パスを追加。

- 2026-05-22 定量確認（30日窓, min=20）:
  - shortage 4 -> 3 に改善。
  - 解消: `offering_or_dilution`
  - 残り不足:
    - `downward_revision_dividend_cut` (7/20)
    - `weak_earnings_or_guidance` (14/20)
    - `upward_revision_highest_profit` (16/20)

- 補足:
  - `run_harvest_backfill.py` のフル実行は長時間化するため、運用上は nightly 実行＋日中は差分実行で回す。
  - 次回は不足3タイプ向けに、TDNET分類語彙の追加とKabutan側の同義語補完を優先する。
- 追加（2026-05-22 夕方）:
  - TDNET分類語彙を拡張（`upward_revision_highest_profit` / `downward_revision_dividend_cut` / `weak_earnings_or_guidance` の取りこぼし低減）。
  - 対象: `scripts/investment/collect/collect_tdnet_disclosures.py`, `scripts/investment/signals/build_market_signals_from_batches.py`
  - 備考: 当日TDNET新規rowは0件のため、今回反映は将来データ・既存再分類時に効く。
- 追加（2026-05-22 夜）: 母数評価テーブルの基準を `signals` から `backtest_outcomes` に変更。
  - 変更ファイル: `scripts/investment/analysis/report_signal_type_coverage.py`
  - 理由: 収集実態（seed由来シグナル母集団）に対して `signals` はサブセットで、shortage判定が過度に厳しく出ていたため。
  - 再集計結果（2026-05-22, 30日, min=20）: total=732, shortages=2 -> material内訳確認で実質不足は `downward_revision_dividend_cut` のみ（19/20）。
- 追加（2026-05-22 夜2）: coverage判定をタイプ別ソース対応へ拡張。
  - 背景: `offering_or_dilution` は `backtest_outcomes` 経路に十分乗らず、実収集量と乖離して不足誤判定していた。
  - 対応: `scripts/investment/analysis/report_signal_type_coverage.py`
    - 既定は `backtest_outcomes` 件数で集計。
    - `offering_or_dilution` のみ `tdnet_disclosures.category` 件数を採用。
    - `--shortage-ratio` 導入（既定0.95）で near-shortage を不足扱いから分離。
  - 結果（2026-05-22, 30日, min=20, ratio=0.95）: shortages=0。
- 追加（2026-05-22 夜3）: SBI銘柄ページ由来の信用可否自動更新を実装。
  - 新規: `scripts/investment/collect/collect_credit_status_auto.py`
  - 対象: 当日 `signals/entry_candidates` に出た銘柄のみ（fallback 1日）
  - 保存: `credit_status_rows` に `source_kind=auto_sbi`, `buy_status`, `sell_status` を upsert
  - 優先: 既存 `manual_*` は上書きしない（manual優先維持）
  - スケジューラ接続: `inv-scenario` の `build_opening_scenarios.py` 直前で実行
  - 注意: 本環境では外部ネットワーク制約で dry-run 取得エラーのため、実ページ抽出精度は本番環境で要確認
- 追記（2026-05-22 深夜）: 閾値調整は来週再分析する。
  - 対象: n=1許容閾値（現行: score>=90, winRate>=70）
  - 判定軸: 件数 / 勝率 / 平均リターン / 最大DD
  - 今週は閾値を固定し、勝率目安データの母数拡大を優先する。

- 今週の優先タスク（母数拡大）
  1) rule_dashboard_rows の集計窓を 30日だけでなく 60/90日へ拡張して比較可能にする
  2) watch実績の T+1/T+5 充填率を日次で監視し、欠損を解消する
  3) unknown系シグナルの再分類を継続して有効母集団へ変換する

- 2026-05-22: investment.db テーブル用途棚卸しを追加（doc/task/investment-table-usage-20260522.md）。未稼働6テーブル（board/margin/market/sector/sector_market/technical）は現行必須経路に未接続として整理。

- 2026-05-22: フェーズ1計測を実装。scripts/investment/analysis/report_signal_pipeline_kpi.py を追加し、漏斗KPI（raw/tdnet/signals/entry/scenario）、signals/tdnet変換率週比較アラート、active universeのprice欠損率アラートを collection_artifacts(artifact_key=signal_pipeline_kpi) へ保存。run_ops_scheduler.py の night/inv-evening に接続。

- 2026-05-22: フェーズ2 step1を反映。run_ops_scheduler.py の kabutan収集強度（discover-latest/max-pages）を+25%相当に引き上げ、inv-scenario の collect_credit_status_auto --max-tickers を 30→50 へ拡張。

- 2026-05-22: フェーズ3実装。report_weekly_tuning_review.py を追加し、weekly_tuning_review を collection_artifacts へ保存。night スロットに接続して7日窓レビュー（watch/trade、low-sample、reject偏在、credit unknown）を自動生成。

- 2026-05-23: 3営業日暫定判定を追加（decide_collection_intensity.py）。signal_pipeline_kpi + weekly_tuning_review を用いて maintain/intensify/rollback を日次判定し、collection_intensity_decision として保存。nightスロットへ接続。

- 2026-05-23: 追加懸念1-5を実装。1) decide_collection_intensity.py に祝日対応営業日判定（jpholiday優先/未導入時fallback）を追加。2) collection_intensity_decision に action_plan（maintain/intensify/rollbackの推奨差分）を追加。3) weekly実行を run_backtest_weekly_inner.ps1 に分離し、失敗時に failed_step を例外へ含めて task-scheduler.log で特定可能にした。4) render_ops_kpi_summary_discord_message.py + post_ops_kpi_discord.ps1 を追加し、night後にKPI最小サマリ1メッセージ通知を追加。5) report_signal_pipeline_kpi.py に signal_type別変換率監視とtype別drop alertを追加。

- 2026-05-24: ゆるい巡回再収集を運用化。scripts/ops/run_harvest_window.ps1 を追加し、週次30日(run_harvest_weekly_recent30.ps1) と月次60日ローテ3本(run_harvest_monthly_rot_a/b/c.ps1) を追加。register_harvest_rotation_tasks.ps1 でスケジューラー登録可能にした。

- 2026-05-24: 母数強化3施策を追加。1) 週次365日バックフィル枠 run_harvest_weekly_samples365.ps1 と登録スクリプト反映。2) run_harvest_backfill.py に shortage>=2 時の追加深掘りパス（tdnet/kabutan増量）を実装。3) weekly本体(run_backtest_weekly_inner.ps1) に fill_market_outcomes --seed-list rough_backtest_full を明示追加。

- 2026-05-24: Discord Task Channel Botを実装（sync_tasks_channel_bot.py）。DISCORD_TASK_CHANNEL_ID + DISCORD_TASKS_BOT_TOKENで監視し、discord_task_eventsへ記録、投資系日本語短縮コマンドを実行可能化。poll時の定期ノイズ投稿は停止（アクション時返信のみ）。詳細: doc/task/discord-task-channel-bot-20260524.md

- 2026-05-24: Memoryを汎用化のため ops.db へ移設。init_ops_db.py に agent_memory_events / discord_task_events を追加し、sync_tasks_channel_bot.py は --task-db/--memory-db（既定=data/ops.db）へ切替。migrate_memory_to_ops_db.py を追加。
