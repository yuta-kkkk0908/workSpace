# 2026-06-15 ExitAnalyzer 設計

## 目的

- 出口まわりのボトルネックを、収集・分析・処理の3面から継続観測する
- `exit timing` の単発レポートではなく、出口品質の監視レイヤーとして扱う
- `entry` 側の評価やシグナル採用ロジックとは責務を分離する

## 背景

- 既存実装には `analyze_exit_timing.py` があるが、役割は保有期間傾向の把握に留まっている
- `post_open_trade_followups_bot.py` は未 exit の個別フォローアップを行う
- `sync_scenario_replies_bot.py` は Discord 返信を DB に反映する
- しかし、出口に関する滞留・遅延・偏り・同期失敗をまとめて見る統合ビューがない

## 役割定義

- ExitAnalyzer は「出口の意思決定そのもの」を行わない
- ExitAnalyzer は「出口の処理状況と品質を可視化する」
- ExitAnalyzer は「前倒し/延長/手仕舞い方針の検討材料」を出す
- ExitAnalyzer は「売買助言」にはしない

## 観測対象

### 収集

- exit 返信が来ていない未 exit 建玉
- open pending / open partial の滞留件数
- follow-up が必要なシナリオスレッドの残存数

### 分析

- `T+1 / T+5 / T+20` の勝率と平均リターン
- 参考窓として `T+3 / T+10` の勝率と平均リターン
- 保有期間別の傾向
- `trade / watch / paper_trade_only` の差分
- `tp / sl / time / manual / cancel` の exit 理由分布

### 処理

- Discord 返信同期の遅延
- 夜間バッチの実行時間
- backlog の増加
- 投稿失敗や再送滞留

## 入力データ

- `paper_trades`
- `scenario_messages`
- `scenario_reply_events`
- `backtest_outcomes`
- `topics/investment-research/inbox/*-paper-trade-exit-timing.md`
- 必要に応じて `price_path_json`

## 出力

- `topics/investment-research/inbox/YYYY-MM-DD-exit-analyzer.md`
- `topics/investment-research/inbox/YYYY-MM-DD-exit-analyzer.json`
- Discord 投稿用の短文

### 出力契約

- `T+1 / T+5 / T+20` は主分析窓
- `T+3 / T+10` は `price_path_json` 由来の参考窓
- `T+3 / T+10` は単独で判定せず、主分析窓の補助比較として扱う
- JSON は `collection` / `analysis` / `processing` を分け、Discord 文面はその要点だけを抜粋する
- Markdown は人間向けの確認用、JSON は downstream 連携用の正本にする
- 追加の診断軸として `mode` / `exit_reason` / `age_bucket` / `stuck` を持たせる
- `mode` / `exit_reason` / `age_bucket` は、件数と主分析窓の勝率・平均リターンを併記する
- `ticker` / `side` も同様に件数と主分析窓の勝率・平均リターンを併記する
- `mode` と `age_bucket` の組み合わせも出して、悪化している層を一段深く特定できるようにする
- `mode` と `age_bucket` の上位層については、`exit_reason` を閉じた建玉に限定して掘り、滞留と損益の両方で原因を追えるようにする
- `mode` と `age_bucket` の上位層については、`status` も同時に見て、未処理/処理済みの偏りを追えるようにする
- `age_bucket` と `status` の組み合わせも出して、滞留の偏りを直接見えるようにする
- `stuck` は未 exit の滞留観測に限り、件数・滞留日数・pending 件数を示す
- Discord 文面は代表的な層だけを1行で抜粋し、詳細は Markdown / JSON を正とする

## 主要指標

- `open_trade_count`
- `open_trade_age_days`
- `exit_sync_lag_minutes`
- `pending_exit_count`
- `exit_reason_mix`
- `t1_t5_t20_exit_quality`
- `t3_t10_reference_quality`
- `stuck_trade_count`
- `followup_backlog_count`
- `ticker_breakdown`
- `side_breakdown`
- `mode_breakdown`
- `mode_age_breakdown`
- `mode_age_exit_reason_breakdown`
- `mode_age_status_breakdown`
- `age_status_breakdown`
- `exit_reason_breakdown`
- `age_breakdown`
- `stuck_breakdown`

## 判定

- `OK`
  - 未 exit の滞留が少なく、同期遅延も許容範囲
- `WARN`
  - 未 exit が増加、あるいは保有期間が偏る
  - 返信同期や投稿再送に遅延がある
- `ALERT`
  - exit backlog が継続増加
  - 未 exit の古い建玉が閾値超過
  - exit 失敗が連続

## 閾値の初期案

- 推奨保有期間 + 1 日を超えた未 exit は `WARN`
- 推奨保有期間 + 2 日を超えた未 exit は `ALERT`
- exit 返信の同期遅延が 3 時間超で `WARN`
- `open_pending_outcome` が連続増加で `WARN`
- `manual` exit の比率が急増したら `WARN`
- `T+3 / T+10` は単独でアラート判定しない
- `T+3 / T+10` は `T+1 / T+5 / T+20` の補助比較に使う

## 非目標

- ExitAnalyzer は entry の昇格/降格を判定しない
- ExitAnalyzer は `scenarioTier` を変えない
- ExitAnalyzer は scheduler health と責務を混ぜない
- ExitAnalyzer は Discord 通知経路の障害調査そのものを置き換えない

## 実装方針

1. 既存の `analyze_exit_timing.py` は残す
2. ExitAnalyzer はその上位概念として追加する
3. 最初は夜間の読み取り専用レポートにする
4. その後、週次レビューと Discord 出力を追加する
5. ロジックの根拠はこの文書に固定し、個別の実装で勝手に増やさない

## 既存関連箇所

- `scripts/investment/backtest/analyze_exit_timing.py`
- `scripts/investment/backtest/analyze_paper_trade_stats.py`
- `scripts/investment/backtest/generate_trade_watch_weekly_review.py`
- `scripts/investment/analysis/exit_horizon_utils.py`
- `scripts/investment/analysis/report_exit_analyzer.py`
- `scripts/investment/backtest/fill_market_outcomes.py`
- `scripts/data/ingest_investment_db.py`
- `scripts/investment/analysis/report_scenario_tracking_card.py`
- `scripts/notify/post_open_trade_followups_bot.py`
- `scripts/notify/sync_scenario_replies_bot.py`
- `scripts/notify/post_exit_analyzer_discord.ps1`

## 受け入れ基準

- ExitAnalyzer の出力を見れば、出口の詰まりが収集・分析・処理のどこにあるか分かる
- 既存の exit timing レポートは壊さない
- entry 側の実装にロジックが逆流しない
- Discord 出力は短く、判断に必要な差分だけを載せる
