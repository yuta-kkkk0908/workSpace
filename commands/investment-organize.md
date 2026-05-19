# Command: investment-organize

## Purpose
`investment-research` に蓄積された daily 情報と market signals を整理し、未整理シグナルの結果確認、読解 lesson、次に見る候補を更新する。

この command は売買助言ではなく、投資情報の読解、整理、検証ログの更新を目的とする。

## Trigger
- 投資情報の整理
- 投資整理
- シグナルチェック
- 市場シグナルチェック
- market signal check
- investment organize

## Required Inputs
- `date`
  - 指定がなければ現在日付を使う

## Optional Inputs
- `unit`
  - 指定がなければ `unorganized-and-signal-check`
  - `unorganized`
  - `signal-check`
  - `technical-margin-check`
  - `sector-pattern-check`
  - `t20-swing-check`
  - `entry-readiness-check`
  - `summary`
  - `all`
- `mode`
  - `proposal`
  - `apply`
- `source_ids`
- `max_items`
- `budget`
  - `adaptive`
  - `lean`
  - `balanced`
  - `deep`

## Default Topic
- `topics/investment-research`

## Read Scope
- `AGENT.md`
- `commands/investment-organize.md`
- `commands/market-signal.md`
- `topics/investment-research/topic-manifest.json`
- `topics/investment-research/index.md`
- `topics/investment-research/summary.md`
- `topics/investment-research/decisions.md`
- `topics/investment-research/signal-rules.md`
- `topics/investment-research/tag-taxonomy.md`
- `topics/investment-research/tag-index.md`
- `topics/investment-research/tag-index.json`
- `topics/investment-research/tasks.json`
- `topics/investment-research/sources.json`
- `topics/investment-research/inbox/*`

## Write Scope
- `topics/investment-research/summary.md`
- `topics/investment-research/decisions.md`
- `topics/investment-research/tasks.json`
- `topics/investment-research/sources.json`
- `topics/investment-research/inbox/*market-signals*.md`

## Execution Mode
- `proposal`
- `apply`

## Execution Units
## Python Script Map
投資系 Python の詳細な入出力と実行順は `scripts/INVESTMENT.md` を正本として参照する。

主な実行レーン:
- `make investment-adaptive`: daily後の軽量索引更新。通常はこれでよい。
- `make investment-rule-check DATE=YYYY-MM-DD`: 既存データからルール候補を軽く確認する。
- `make investment-backtest-expand DATE=YYYY-MM-DD`: deep用。サンプル収集からrule history/tag-indexまでまとめて回す。
- `make investment-signal-missing DATE=YYYY-MM-DD`: market-signals の必須項目欠損を検知する品質ゲート。
- `make investment-entry-candidates DATE=YYYY-MM-DD`: market-signals から long/short 監視候補を抽出する。

## Rate Budget Policy
レート残量が厳しい場合は、投資分析を止めるのではなく、重い処理を分離する。

既定は `adaptive` とする。
投資情報は、毎回フル分析せず、軽量トリアージから深掘り対象を昇格させる。

### adaptive
- まず `lean` 相当の core check を行う
- 各候補を `deep_dive_now` / `deep_queue` / `no_change` に分ける
- `deep_dive_now` は対象が少数で、当日判断に関わるものだけに限定する
- `deep_queue` は、レート回復後または明示依頼時に `deep` で処理する
- rule dashboard / rule history は読むが、再集計は必要時だけにする
- tag-index を参照し、同種材料の過去事例が多いものは既存パターンとして扱い、少ない/例外的なものだけ深掘りに回す
- Python側は `make investment-adaptive` を基本とし、タグ索引だけ更新する

昇格条件:
- active rule に該当する新規シグナル
- watch rule の例外または急な件数増
- T+1 / T+5 / T+20 の期限到来 outcome
- 外部要因と個別値動きが食い違う相対強弱
- short 側の `strict_short_signal` / `return_short_wait` / `exit_or_buy_avoid`
- 出来高急増、大陰線/大陽線、寄り天/引け急変など、短期検証価値が高い値動き
- 決算、下方修正、減配、希薄化、TOB/M&A、不祥事、規制など、材料として後から効きやすい開示

### lean
- 対象は、期限到来した T+1 / T+5 / T+20、当日重要シグナル、最新 `daily-rule-brief` の反映に絞る
- `topics/investment-research/inbox/*` の全量読みに行かず、日付指定ファイル、最新 daily、最新 market-signals、最新 rule dashboard / history を読む
- `fill_market_outcomes.py`、`fill_technical_context.py`、`fill_borrow_context.py` など既存データを機械的に補完できるスクリプトは必要時のみ実行し、エージェントによる長い読み解きは避ける
- `collect_kabutan_*`、過去バックフィル、unknown一括補完、週次/月次レポートは実行しない
- 出力は「更新した件数」「重要な変化」「次に深掘りする候補」に絞る

### balanced
- 通常の `unorganized-and-signal-check` と軽い rule dashboard 確認を行う
- 重いバックテスト拡張は明示依頼時のみ実行する

### deep
- バックテスト拡張、unknown補完、ショート/ロング再分類、rule history更新までまとめて行ってよい
- 実行前に対象期間、対象件数、出力ファイルを短く宣言する
- Python側は `make investment-backtest-expand DATE=YYYY-MM-DD` を使う

### unorganized
`sources.json` の `status: new` のうち、daily / market-signal を読み、正本に反映すべき変化を整理する。

### signal-check
`inbox/*market-signals*.md` の open signals を読み、T+1 / T+5 / T+20 の確認時期に来た outcome を追記する。

### unorganized-and-signal-check
`unorganized` と `signal-check` を両方行う。既定の実行単位。

### summary
蓄積したシグナルから、読めた傾向、外れた理由、次に見るべき銘柄/シグナル種別を `summary.md` / `tasks.json` に反映する。

### market-context
daily メモに保存された市場地合い、セクター強弱、出来高異常、悪材料、見送り理由を読み、market signals の outcome 解釈に使える形で整理する。

確認する観点:
- 個別シグナルの結果が、指数やセクターの追い風/逆風と一致していたか
- 高配当候補に関係する銀行、商社、通信、鉄鋼、海運、不動産、エネルギー、食品、たばこに偏りがあったか
- 出来高急増、年初来高値/安値、寄り天、大陰線などの反応が後日の T+5 / T+20 に影響したか
- 買わなかった理由、利確/撤退理由が後から妥当だったか

### technical-margin-check
Rank上位、弱さが目立つ銘柄、T+1/T+5更新対象について、テクニカルと信用需給を補完する。

優先対象:
- `longSignalRank: A`
- `shortSignalRank: A/B`
- `negative_relative_strength`
- `sell_the_news`
- T+1/T+5/T+20の期限到来銘柄

確認する項目:
- MA5/25/75
- 出来高5日/25日平均、出来高倍率
- RSI、MACD、ボリンジャー
- ローソク足、上ヒゲ/下ヒゲ、大陽線/大陰線
- 年初来高値/安値、直近高値/安値
- 信用買残、信用売残、信用倍率、前週比
- 売建可否、逆日歩、株不足

### sector-pattern-check
蓄積された `sectorPattern.patternKey` を読み、セクターごとの勝ち/負けパターンを集計する。

集計軸:
- externalTriggerType
- sector
- signalType
- technicalPattern
- marginPattern
- longSignalRank / shortSignalRank
- entryReadiness
- T+1 / T+5 / T+20
- missFactor

最初は統計的有意性を求めず、件数、勝ち/負け、外れ理由を表にする。

### rule-check
`signal-rules.md` の暫定ルールを読み、蓄積された market signals / rough backtest / outcome から、昇格、降格、保留、例外を整理する。

確認する観点:
- ルールごとの該当件数
- T+1 / T+5 / T+20 の勝敗
- n<4 から n>=4 へ増えたもの
- 追加データで崩れたもの
- 逆方向に効いた例外
- daily のランク補正に残すべきもの

整理結果は、必要に応じて `signal-rules.md` を更新する。
ただし、サンプルが少ないものは `hypothesis_only` として残し、確定ルールのように扱わない。

自動集計:
- `python3 scripts/investment/analysis/rule_check_market_outcomes.py --date YYYY-MM-DD --min-count 8`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-rule-check-summary.md`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-rule-check-data.json`
- `python3 scripts/investment/analysis/analyze_long_rule_reproducibility.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-long-rule-reproducibility.md`
- ロング側も、該当ルールの出現回数、出現期間、材料タイプ、T+1/T+5/T+20を保存し、再現性を見てから昇格する。
- `python3 scripts/investment/analysis/generate_rule_dashboard.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-rule-dashboard.md`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-daily-rule-brief.md`
- ロング/ショートを共通軸で `active_rule` / `watch_rule` / `hypothesis_only` に分け、daily で表示するルールだけを短く抽出する。
- `python3 scripts/investment/analysis/update_rule_history.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/rule-history.md`
- 出力: `topics/investment-research/rule-history.json`
- ルールごとの出現回数、T+1/T+5/T+20、初回/最新観測日、ステータス履歴を累積管理する。

母数拡張:
- `python3 scripts/investment/collect/collect_kabutan_surprise_signals.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-six-month-rough-backtest-batch-5-kabutan-surprise.md`
- `python3 scripts/investment/collect/collect_kabutan_short_signals.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-six-month-rough-backtest-batch-6-short-negative.md`
- バックテスト母集団は `configs/investment-seeds.json` の seed list を正本にする。
- 通常deepは `rough_backtest_full`、軽量確認は `rough_backtest_light`、short検証は `rough_backtest_short_focus` を使う。
- seedを追加/除外する場合は、Pythonコードではなく `configs/investment-seeds.json` を更新する。
- ネット取得を避ける場合は `CACHE_ONLY=1` または各スクリプトの `--cache-only` を使う。
- その後、`python3 scripts/investment/backtest/fill_market_outcomes.py --date YYYY-MM-DD`、`python3 scripts/investment/analysis/analyze_market_outcomes.py --date YYYY-MM-DD`、`python3 scripts/investment/analysis/analyze_cross_factors.py --date YYYY-MM-DD`、`python3 scripts/investment/analysis/rule_check_market_outcomes.py --date YYYY-MM-DD --min-count 8` の順で再集計する。
- テクニカル指標も更新する場合は、`python3 scripts/investment/backtest/fill_technical_context.py --date YYYY-MM-DD` を `fill_market_outcomes.py` の後に実行する。

テクニカル収集:
- `python3 scripts/investment/backtest/fill_technical_context.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-technical-context-data.json`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-technical-context-summary.md`
- 取得項目: MA5/25/75、MA傾き、RSI14、MACD、ボリンジャー20、20日高値/安値ブレイク、テクニカルパターン。
- short強化では `technical_short_bias`、`breakdown_short_watch`、`bearish_trend_continuation`、`overbought_reversal_watch` を優先確認する。

short用途分離:
- `python3 scripts/investment/analysis/classify_short_use_cases.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-use-case-data.json`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-use-case-summary.md`
- `short_entry_candidate`: 空売り検討候補。
- `buy_avoid_rebound_risk`: 悪材料だが売られすぎで、空売りより買い回避。
- `short_term_event_short`: 希薄化/売出しなど、T+1/T+5中心の短期イベント。
- `exit_or_buy_avoid`: 既存Longの撤退/利確、または新規買い見送り。

short監視準備度:
- `python3 scripts/investment/backtest/fill_borrow_context.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-borrow-context-data.json`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-borrow-context-summary.md`
- JPX公式の制度信用・貸借銘柄一覧を使い、`loan_margin` / `standardized_margin_only` / `not_in_jpx_current_list` を付与する。
- 注意: JPX現時点/as-ofの区分であり、証券会社別の一般信用、日々の売り禁、逆日歩、過去時点の貸借可否は含まない。
- `python3 scripts/investment/analysis/classify_short_readiness.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-readiness-data.json`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-readiness-summary.md`
- `high`: 実監視の最優先。ただし売建可否、貸借、逆日歩、板確認は必須。
- `medium`: 日次監視候補。流動性/出来高はあるが、追加確認が必要。
- `medium_low_liquidity` / `low_liquidity_avoid`: 空売りより買い回避寄り。
- `avoid_short_rebound_risk`: 売られすぎで戻り警戒。戻り売りの再セットアップ待ち。

short日次表示:
- `python3 scripts/investment/analysis/analyze_short_high_readiness.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-high-readiness-review.md`
- `python3 scripts/investment/analysis/generate_short_watch_report.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-watch-report.md`
- `python3 scripts/investment/analysis/analyze_short_chart_windows.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-chart-window-review.md`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-chart-window-data.json`
- `python3 scripts/investment/analysis/analyze_short_chart_window_stats.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-chart-window-stats.md`
- `python3 scripts/investment/analysis/analyze_short_rebound_risk.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-rebound-risk-review.md`
- `python3 scripts/investment/analysis/classify_short_conviction.py --date YYYY-MM-DD`
- 出力: `topics/investment-research/inbox/YYYY-MM-DD-short-conviction-report.md`
- daily本文では `Short Entry Watch` だけを空売り監視候補として出す。
- `Low Liquidity Short Watch` はJPX貸借銘柄だけを表示し、原則として買い回避/警戒寄りに扱う。
- JPX貸借でない低流動性候補は `Buy Avoid / Exit Watch` に落とす。
- `followThrough=yes` はT+1/T+5監視に向く候補、`reboundRiskWithinWindow=yes` は即追随より戻り売り待ち候補として扱う。
- `short-chart-window-stats` で `followThrough` / `reboundRisk` / `shortReadiness` 別のT+1/T+5/T+20を確認し、nが小さいものは仮説扱いにする。
- `avoid_short_rebound_risk` は `short-rebound-risk-review` で、流動性、貸借、出来高、検証窓内の戻りを確認し、ショート除外/戻り売り待ちルールの材料にする。
- `short-conviction-report` では、各ルールの出現回数、出現期間、材料タイプ、T+1/T+5/T+20傾向を確認する。n<8は `hypothesis_only` として扱い、再現性確認中にする。
- `rule-dashboard` では、ロングとショートを同じ表に統合し、再現性があるものだけを日次の主表示に回す。
- `daily-rule-brief` は「今日の情報」の投資欄に差し込む短縮版として使う。
- `rule-history` は、暫定ルールの変化を追う正本として使い、1日だけの結果でルールを過度に変更しない。

### tag-index
market signals に軽量タグを付け、検索・集計・adaptive gate に使う。

自動生成:
- `python3 scripts/investment/analysis/build_investment_tag_index.py`
- 出力: `topics/investment-research/tag-index.md`
- 出力: `topics/investment-research/tag-index.json`

使い方:
- `sig:*` で材料種別を探す
- `dir:*` で long / short / avoid を分ける
- `rank:*` で監視優先度を確認する
- `rule:*` で active / watch / hypothesis を確認する
- `prio:*` で deep 対象を絞る
- `q:*` で未確認や補完対象を拾う

注意:
- タグは売買判断ではなく、検索・集計・深掘りキューの補助。
- Vector検索を導入する場合も、まずこの tag-index を前処理として使う。

### t20-swing-check
T+20到来済みのシグナルを確認し、`swingOutcome` を埋める。

確認する観点:
- 初動高値を超えたか
- MA25を維持したか
- 出来高が継続したか
- T+5から伸びたか
- テーマ化したか
- 外部環境で説明できるか
- 全戻ししたか

### entry-readiness-check
Rankと実際に監視できる状態を分けるため、`entryReadiness` を更新する。

確認する観点:
- direction: long / short / avoid / watch
- readiness: high / medium / low / avoid / unknown
- waitCondition
- invalidation
- stopReason
- timeHorizon

これは売買指示ではなく、後日の検証用に「なぜ見送る/監視するか」を明示するための項目。

### all
全実行単位を行う。

## Signal Check Policy
- 売買推奨はしない
- 結果の追記は、T+0 / T+1 / T+5 / T+20 の窓で行う
- 結果が予想と違った場合ほど `lesson` を残す
- 価格反応は、シグナルそのもの、地合い、セクター、織り込み、流動性に分けて考える
- daily の市場背景を使い、個別材料と相場全体の影響を分けて lesson に残す
- 二次情報だけで判断したシグナルは、可能な限り一次情報へ戻る task を残す
- technicalContext / marginContext / entryReadiness / sectorPattern / swingOutcome が空欄の重要シグナルは、補完対象として残す
- `signal-rules.md` の暫定ルールに該当するかを確認し、該当/例外/保留を lesson に残す

## Output Contract
### proposal
- `target_sources`
- `signals_to_update`
- `summary_updates`
- `task_updates`
- `unresolved_points`

### apply
- `updated_files`
- `organized_source_ids`
- `updated_signal_count`
- `added_lessons`
- `notes`

## Success Criteria
- 未整理の投資情報が正本に反映される
- market signals の outcome が継続的に埋まる
- 次に見るべき候補と学びが明確になる
