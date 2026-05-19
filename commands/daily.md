# Command: daily

## Purpose
ユーザーが「今日の情報」と依頼したときに、daily watch 対象の topic から当日見るべき情報を収集・整理し、短く解説する。

## Trigger
- 今日の情報
- 今日のまとめ
- daily
- daily digest
- 今日見るべき情報
- 今日の情報 deep
- 取り逃し補完

## Required Inputs
- `date`
  - 指定がなければ現在日付を使う

## Optional Inputs
- `topics`
  - 指定がなければ `topic-manifest.json` の `kind: daily-watch` を対象にする
- `mode`
  - 指定がなければ `collect-and-present`
  - `present-only`
  - `collect-and-present`
- `limit_per_topic`
- `include_sources`
- `budget`
  - 指定がなければ `adaptive`
  - `adaptive`
  - `lean`
  - `balanced`
  - `deep`
- `rate_state`
  - `normal`
  - `constrained`
- `need_watch`
  - 指定がなければ `background`
  - `background`
  - `skip`
- `market_signal`
  - 指定がなければ `background`
  - `background`
  - `skip`

## Trigger Word Routing
- `今日の情報`
  - 標準実行。`budget: adaptive` を既定にする
- `今日の情報 deep`
  - 深掘り実行。`budget: deep` を既定にする
- `取り逃し補完`
  - `commands/reminder.md` で不足日を確認したうえで、対象日の daily を補完する

## Default Topics
`topics/` 配下で `topic-manifest.json` の `kind` が `daily-watch` のものを対象にする。

現在の想定:
- `ai-news-watch`
- `investment-research`
- `pokemon-card-watch`
- `tech-stack-reads`

通知専用:
- `product-idea-watch`

## Read Scope
- `AGENT.md`
- `commands/daily.md`
- `templates/present/daily.md`
- `data/*.db`（存在する topic DB。投資は `data/investment.db` を優先）
- `topics/*/topic-manifest.json`
- `topics/{{topic}}/index.md`
- `topics/{{topic}}/summary.md`
- `topics/{{topic}}/decisions.md`
- `topics/{{topic}}/signal-rules.md`（存在する場合）
- `topics/{{topic}}/tag-taxonomy.md`（存在する場合）
- `topics/{{topic}}/tag-index.md`（存在する場合）
- `topics/{{topic}}/tasks.json`
- `topics/{{topic}}/sources.json`
- 必要に応じて `topics/{{topic}}/inbox/*`

## Write Scope
### present-only
- なし

### collect-and-present
- `topics/{{topic}}/inbox/*`
- `topics/{{topic}}/sources.json`
- 必要に応じて `topics/{{topic}}/summary.md`
- 必要に応じて `topics/{{topic}}/decisions.md`
- 必要に応じて `topics/{{topic}}/tasks.json`
- `topics/product-idea-watch/inbox/*`
- `topics/product-idea-watch/sources.json`
- 必要に応じて `topics/product-idea-watch/summary.md`
- 必要に応じて `topics/product-idea-watch/tasks.json`

## Execution Mode
- `proposal`
- `apply`

## Default Behavior
`daily` は、ユーザーが明示的に `present-only` を指定しない限り `collect-and-present` で実行する。

毎回の daily で、確認した情報は topic ごとに短い収集メモとして `inbox/` に保存し、`sources.json` に参照を追加する。
これにより、同じ情報を繰り返し提示するのではなく、topic に日々の情報蓄積を残す。

## DB-First Policy (Mandatory)
`今日の情報` は次の順序を必須とする。

1. DB確認（最優先）
   - topic DB がある場合、まず DB から当日データを取得する。
   - 投資は `data/investment.db` を正本として、`signals` / `entry_candidates` / `daily_digest` を確認する。
   - 非投資 topic は `data/topics.db` の `topic_daily_digest` / `topic_links` を優先参照する。
2. 不足補完（必要時のみ）
   - DB に当日データがない topic のみ、`topics/{{topic}}/inbox/YYYY-MM-DD-*.md` を参照する。
3. 要約生成
   - 可能な限り DB ベースで要約し、補完分だけファイル由来として扱う。
4. 実行報告
   - 出力時に「DB確認済み」「不足補完の有無」を明示する。

禁止事項:
- DB を確認せずに `inbox` のみで `今日の情報` を作成すること。

## Rate Budget Policy
weekly / 5h のレート残量が厳しい場合は、収集の網羅性よりも継続性を優先する。
ユーザーが「低消費」「省エネ」「レート節約」「残量が少ない」「rate constrained」と言った場合、または weekly rate が 50% 未満で次回リセットまで24時間以上ある場合は、`budget: lean` として扱う。
通常は `budget: adaptive` とし、軽量トリアージを常時行い、深掘り条件に該当したものだけ追加調査に回す。

### adaptive
推奨モード。ずっと低消費に固定せず、必要な時だけ投資分析を厚くする。

- daily のベースは `lean` 相当で始める
- 投資情報だけは「ゲート式」で、深掘り条件に該当したものを `deep_queue` に積む
- `deep_queue` に入ったものは、当日レートに余裕があれば限定深掘りし、余裕がなければ次回 `deep` 候補として保存する
- product idea の裏収集、unknown 一括補完、週次/月次レポートは、adaptive では自動実行しない
- 出力では「今日確認したもの」「深掘り昇格」「後回し」を分ける

投資の深掘りゲート:
- 外部トリガーが `risk_on` / `risk_off` / `rates_move` / `fx_move` / `geopolitics` などで市場反応を伴う
- 当日重要開示が `earnings_positive`、下方修正、減配、希薄化、TOB/M&A、大型受注、規制/不祥事に該当する
- `daily-rule-brief` の `active_rule` に該当する
- `rule-history` 上の `watch_rule` で、件数が増えた、または例外が出た
- T+1 / T+5 / T+20 の期限到来 outcome がある
- 強い地合いで上がらない、弱い地合いで下がらないなど、相対強弱の例外が出た
- short 側で `strict_short_signal`、`return_short_wait`、`exit_or_buy_avoid` が出た

### lean
低消費モード。毎日継続するための最小構成。

- 読むファイルは `AGENT.md`、`commands/daily.md`、`templates/present/daily.md`、対象 topic の `summary.md` / `decisions.md` / `tasks.json` / 当日と直近1〜2日の inbox に絞る
- `sources.json` は必要な topic の末尾付近と重複 path 確認だけに使い、全量を読み込まない
- `inbox/*` の全探索を避け、日付指定、最新 daily、最新 market-signals、最新 `daily-rule-brief` を優先する
- topic ごとの新規収集は原則 1〜3件までにする
- AIニュース、技術記事、ポケモンカードは「重要変化があるか」の確認を優先し、変化なしは確認済み `N/C` でよい
- 投資は外部トリガー、市場地合い、重要開示、期限到来 outcome、最新 `daily-rule-brief` の反映を優先する
- `product-idea-watch` の裏収集は原則 `skip`。ただし、ユーザーが明示した場合だけ軽量に1〜3件追加する
- バックテスト拡張、未知項目の一括補完、大量の過去検証、週次/月次レポート生成は実行しない
- 出力は「読む価値がある差分」に絞り、詳細な全項目羅列を避ける

### balanced
通常モード。日次として必要な収集と蓄積を行う。

- daily watch topic を一通り確認する
- `need_watch: background` と `market_signal: background` を実行してよい
- 投資の outcome や rule dashboard は、既存成果物がある場合に反映する
- 深いバックテストや大量補完は、ユーザーが明示した場合だけ実行する

### deep
深掘りモード。レートと時間に余裕があるときだけ使う。

- 新規調査、バックフィル、unknown 補完、ルール再集計、週次/月次レポートをまとめて進めてよい
- `investment-backtest-expand` 相当の重い処理は `deep` または明示依頼時のみ実行する
- 実行前に、何をどこまで進めるかを短く宣言する

### Rate Saving Defaults
`budget: lean` では、次を既定値にする。

- `need_watch: skip`
- `market_signal: background_light`
- `limit_per_topic: 3`
- `include_sources: essential`
- `output_detail: concise`

`budget: adaptive` では、次を既定値にする。

- `need_watch: skip`
- `market_signal: triage`
- `limit_per_topic: 3`
- `include_sources: essential`
- `output_detail: concise`
- `investment_deep_dive: gated`

また、ユーザーが明示的に `need_watch: skip` を指定しない限り、`product-idea-watch` の軽量な裏収集も実行する。
ただし、daily 本文には通常出さず、分析閾値・重要な束の増加・ユーザーが明示的に求めた場合だけ通知する。

さらに、ユーザーが明示的に `market_signal: skip` を指定しない限り、`investment-research` の市場シグナル読解ログも軽量に更新する。
当日シグナルの仮説を残し、過去シグナルの T+1 / T+5 / T+20 の結果が確認できる場合は追記する。

投資情報では、朝の情報取得時に `external-trigger` も確認する。
米国要人発言、FRB高官発言、地政学、金利、為替、原油、米国株、SOX、日経先物を確認し、ニュースから市場データ反応、日本株セクター影響まで変換する。
保存先は `topics/investment-research/inbox/YYYY-MM-DD-external-triggers.md` とし、daily 本文では重要なものだけ短く出す。

投資情報では、個別材料だけでなく、その日の市場背景も保存する。
これにより、後日の検証で「シグナル自体が効いたのか」「地合い・セクター・需給に助けられた/負けたのか」を分けて読めるようにする。
銘柄情報と市場シグナルは、デイトレ/スイング向けの短期材料把握にも使う。

投資情報では、`topics/investment-research/signal-rules.md` が存在する場合は必ず読む。
daily の投資ランク付けでは、暫定ルールにある材料、地合い、信用需給、出来高、ローソク足、セクターの組み合わせを確認し、`longSignalRank` / `shortSignalRank` / 見送り理由に反映する。
ただし、暫定ルールは売買判断ではなく監視優先度と確認観点であり、n<4 の仮説は強く扱わない。
`topics/investment-research/inbox/YYYY-MM-DD-daily-rule-brief.md` または最新の `*-daily-rule-brief.md` がある場合は参照し、再現性のある `active_rule` と検証中の `hypothesis_only` を分けて表示する。
`topics/investment-research/rule-history.md` がある場合は、単日の印象より累積傾向を優先し、出現回数が少ないルールは「仮説」と明示する。
`topics/investment-research/tag-index.md` がある場合は、同種シグナルの既存タグを参照し、`deep_queue` と `no_change` の切り分けに使う。

## Collection Record Policy
`collect-and-present` では、daily watch 対象 topic ごとに次を行う。

1. 当日確認した情報を `topics/{{topic}}/inbox/YYYY-MM-DD-daily.md` に保存する
2. 同じ日に同じ topic の daily メモがある場合は、新規ファイルを増やさず既存ファイルを更新する
3. `sources.json` に daily メモへの source entry を追加する
4. 既に同じ `path` の source entry がある場合は重複追加せず、必要に応じて既存 entry を更新する
5. 重要な変化があった場合のみ `summary.md` / `tasks.json` / `decisions.md` を更新する

## Background Need Watch Policy
`collect-and-present` では、daily watch 対象 topic の収集後に `product-idea-watch` も軽量に更新する。

`budget: lean` の場合は、ユーザーが明示しない限り skip する。

1. `commands/need-watch.md` の制約に従う
2. 1回あたりの巡回は5〜10か所程度に抑える
3. 投稿本文を保存せず、不満パターン、要望、既存代替、作れそう度、検証方法だけを保存する
4. 保存先は `topics/product-idea-watch/inbox/YYYY-MM-DD-daily-background-need-watch.md`
5. 同じ日の background need-watch メモがある場合は、新規ファイルを増やさず既存ファイルを更新する
6. `topics/product-idea-watch/sources.json` に source entry を追加または更新する
7. daily 本文では、閾値到達や分析候補の増加だけを短く通知する
8. 既に分析閾値を超えている場合でも、収集自体は継続し、通知は「分析待ちが増えた」程度に留める

## Background Market Signal Policy
`collect-and-present` では、daily の投資情報収集とあわせて `investment-research` の market signal log も軽量に更新する。

`budget: adaptive` の場合は `triage` として扱い、次の3段階に分ける。

1. core check
   - 外部トリガー、市場地合い、重要開示、期限到来 outcome、最新 rule brief を確認する
   - 新規調査は重要変化に限る
2. gate decision
   - `deep_dive_now` / `deep_queue` / `no_change` に分ける
   - `deep_dive_now` は、当日中に見る価値が高く、かつ対象が少数の場合だけ行う
   - `deep_queue` は `topics/investment-research/tasks.json` または当日 daily メモの `Next Deep Work` に残す
3. daily presentation
   - 本文には `deep_dive_now` と重要な `deep_queue` だけ出す
   - `no_change` は確認済み `N/C` として短く扱う

`budget: lean` の場合は `background_light` として扱い、次だけを行う。

- 当日の重要開示または市場変化が明確なものだけ記録する
- T+1 / T+5 / T+20 の期限到来分だけ確認する
- 既存の `daily-rule-brief` / `rule-history` を参照し、新規の大規模再集計はしない
- 未確認や対象外は「低消費モードのため深掘り保留」と明示する

1. `commands/market-signal.md` の制約に従う
2. 当日の一次情報シグナルを `topics/investment-research/inbox/YYYY-MM-DD-market-signals.md` に保存する
3. 同じ日の market signal メモがある場合は、新規ファイルを増やさず既存ファイルを更新する
4. `topics/investment-research/sources.json` に source entry を追加または更新する
5. 過去の open signals が T+1 / T+5 / T+20 の確認時期に来ていれば、結果と lesson を追記する
6. daily 本文では、重要な新規シグナルや期限到来した検証結果だけを短く通知する
7. 売買推奨ではなく、シグナル読解と結果検証のログとして扱う
8. daily の市場シグナルチェックは継続実行する。ユーザーが明示的に `market_signal: skip` を指定しない限り省略しない
9. 新規シグナルが少ない日でも、過去シグナルの T+1 / T+5 / T+20 outcome 確認は行う
10. market-signal では、可能な範囲で `technicalContext`、`marginContext`、`entryReadiness`、`timeOfDayPlan`、`sectorPattern` を記録する
11. 適時開示は自社株買いに偏らせず、業績/決算、配当、資本政策、M&A/TOB、月次/KPI、大型受注、提携、リスク/不祥事、外部制度要因まで広く拾う
12. 株価に効くか不明な開示でも、後から「反応なし」を学ぶため、代表的なものは `neutral_watch` として保存してよい
13. daily 本文に出すのは重要なものだけでよいが、inbox には「拾ったが表示しなかった材料」の要約を残す
14. `signal-rules.md` の暫定ルールを参照し、ルールに該当した場合は `ruleHits` / `rankAdjustmentReason` / `watchReason` として保存する
15. ルールに反する値動きが出た場合は、暫定ルールの検証材料として `ruleException` または `lessonCandidate` に残す
16. セクターproxyが取得できる場合は `sectorMarketContext` を確認し、市場全体の地合いとは別にセクター追い風/逆風/相対強弱を残す
17. `generate_rule_dashboard.py` / `update_rule_history.py` の結果がある場合は、daily 表示に使える再現性ルールを `ruleDashboard` として参照する
18. `strict_short_signal` などサンプル不足のショートルールは、空売り候補ではなく検証中ルールとして扱う
19. `tag-taxonomy.md` に従い、可能な範囲で `src:*` / `sig:*` / `dir:*` / `rank:*` / `rule:*` / `prio:*` / `q:*` のタグを付ける
20. daily 後に可能なら `python3 scripts/investment/analysis/build_investment_tag_index.py` を実行し、軽量検索用の `tag-index` を更新する
21. daily 後に可能なら `make investment-entry-candidates DATE=YYYY-MM-DD` を実行し、`entry-candidates` を保存する
22. `entry-candidates` は売買助言ではなく、long/short監視候補の抽出ログとして扱う

## Background External Trigger Policy
`collect-and-present` では、投資情報の前提として `external-trigger` も軽量に更新する。

1. `commands/external-trigger.md` の制約に従う
2. 保存先は `topics/investment-research/inbox/YYYY-MM-DD-external-triggers.md`
3. 同じ日の external trigger メモがある場合は、新規ファイルを増やさず既存ファイルを更新する
4. `topics/investment-research/sources.json` に source entry を追加または更新する
5. 収集順は「ニュース検知 → 市場データ反応 → 日本株セクター影響 → rank補正」とする
6. 米国要人発言、FRB高官発言、地政学、関税/規制、米株、SOX、米10年債、ドル円、日経先物、原油を優先する
7. daily 本文では、重要な外部トリガーと日本株セクター影響だけを短く表示する
8. market-signal のランク付けでは、external trigger の `rankImpact` を参照する
9. 二次情報のみの場合は `secondary_only` と明示し、市場データ反応がない場合は過大評価しない
10. セクターETF/指数proxyで確認できる場合は、`sectorMarketContext` として個別銘柄のセクター追い風/逆風を保存する

## Investment Daily Context Policy
`investment-research` の daily メモでは、可能な範囲で次の市場背景を保存する。

1. 市場全体
   - 日経平均、TOPIX、グロース250など主要指数の方向
   - 売買代金、出来高、値上がり/値下がり銘柄数などの市場の厚み
   - 為替、米株、米金利、国内金利、政策イベントなどの外部要因
   - 米国市場、世界市場、日経先物、CME日経平均先物、ドル円、米10年債、原油を確認する
   - 特に半導体/AI/グロースはNASDAQとSOX、輸出株はドル円、銀行/不動産/高配当は金利、商社/海運/エネルギーは原油・資源価格を見る
   - 米国要人発言やFRB高官発言があった場合は、発言内容だけでなく米株、金利、為替、先物がどう反応したかを保存する
2. セクター強弱
   - 高配当候補に影響しやすい銀行、商社、通信、鉄鋼、海運、不動産、エネルギー、食品、たばこを優先する
   - セクター全体の追い風/逆風を、個別銘柄の材料と分けて記録する
3. ウォッチリスト変化
   - 保有中、買い候補、利確候補、買い戻し候補、監視外だが材料あり、に分ける
   - 配当目的の保有銘柄は、ユーザーが明示的に依頼するまで日次ウォッチ対象にしない
   - JT は保有ウォッチではなく、配当株の比較基準としてのみ扱う
   - ユーザーが保有銘柄を列挙した場合でも、既定では売買監視ではなく配当継続性の確認対象として扱う
4. 出来高を伴う異常値
   - 年初来高値/安値、出来高急増、大陽線/大陰線、寄り天、引け急変を記録する
   - 好材料なのに上がらない、悪材料なのに下がらない反応は、重要な読解材料として残す
   - デイトレ/スイング用途では、寄り付き反応、前場/後場の形、引け強弱を優先して残す
5. 悪材料/売りシグナル
   - 下方修正、減配、希薄化、減損、決算遅延、監査法人変更、不祥事、弱いガイダンスを確認する
   - 売りシグナルは、空売り候補だけでなく、買い回避、利確、撤退、ヘッジ候補として扱う
   - `shortUseCase` として `short_entry_candidate` / `buy_avoid_rebound_risk` / `short_term_event_short` / `exit_or_buy_avoid` を分ける
   - `shortReadiness` として `high` / `medium` / `medium_low_liquidity` / `low_liquidity_avoid` / `avoid_short_rebound_risk` を分ける
   - `borrowStatus` として JPX公式ベースの `loan_margin` / `standardized_margin_only` / `not_in_jpx_current_list` を確認する
   - `shortReadiness: high/medium` のみ「空売り監視候補」として本文に出し、それ以外は「買い回避/撤退/見送り」に分ける
   - `shortReadiness: high` でも、当日売り禁、逆日歩、証券会社側の売建可否、板、寄り付き後の反応が未確認なら `確認待ち` と明示する
   - `avoid_short_rebound_risk` は空売り監視候補に混ぜず、「戻り売り待ち」に分ける
   - `medium_low_liquidity` / `low_liquidity_avoid` は「低流動性ショート注意」に分け、実売買では板/約定/逆日歩/売建可否の確認待ちにする
   - `short_term_event_short` は「短期イベント候補」に分け、T+1/T+5中心で扱い、T+20まで引っ張らない
   - `hard_no_short_strong_rebound` は「戻りが強いため即ショート除外」として扱う
   - `return_short_wait_after_setup` は「戻り失敗後の再監視」として扱う
   - `buy_avoid_no_system_short` は制度信用ショート候補にせず、買い回避/材料学習用に回す
6. 見送り理由
   - 高利回りだが業績悪化、増配が一過性、株価上昇済み、出来高が薄い、セクター逆風、決算前、チャート崩れなどを残す

投資 daily 本文では、上記をすべて詳細表示する必要はない。
ただし、`inbox/YYYY-MM-DD-daily.md` には、後から検証できる最低限の要約とURLを保存する。

### External Context Ranking Policy
投資シグナルをランク付けする前に、外部環境を `tailwind` / `headwind` / `mixed` / `neutral` / `unknown` で読む。

外部環境の扱い:

- 米国市場と世界市場が強い場合、上昇した銘柄は「個別材料だけで上がった」と断定しない
- 米国市場と世界市場が弱い場合、下落した銘柄は「個別材料が弱い」と断定しない
- 追い風地合いで上がらない銘柄は `negative_relative_strength` として重視する
- 逆風地合いで下がらない銘柄は `relative_strength` として重視する
- Rank C は、`company_signal_weak` / `external_headwind` / `sector_headwind` / `technical_breakdown` / `low_liquidity` のどれが主因かを残す

daily の投資セクションでは、必要に応じて「外部環境による補正」を短く説明する。

## Investment Time Operation Policy
投資情報は朝に取得するほど価値が高い。
夜に実行した場合も、次の朝に使えるよう「翌営業日の朝に何を見るか」を残す。

### 朝 / before_open
- external-trigger を確認する
- 米国要人発言、FRB高官発言、地政学、米国株、SOX、米10年債、ドル円、日経先物、原油を確認する
- 日本株セクター別に tailwind / headwind を仮説化する
- 寄り前に見る銘柄を `timeOfDayPlan.beforeOpen` に残す

### 前場 / morning_session
- 寄り付きギャップ、寄り天/寄り底、出来高倍率、前場高値/安値を確認する
- 外部トリガーのセクター仮説と実際の値動きが一致したかを記録する

### 後場 / afternoon_session
- 前場の強さが継続したか、後場で反転したかを確認する
- スイングに残せる形か、日計り止まりかを `entryReadiness` に反映する

### 引け後 / after_close
- 適時開示、決算、IRを確認する
- 翌営業日の `market-signal` 候補を作る
- T+0/T+1/T+5/T+20の更新対象を整理する

## Investment Technical And Margin Policy
daily の市場シグナル確認では、Rank上位または弱さが目立つ銘柄に限り、次を優先取得する。

- technicalContext: MA5/25/75、出来高5日/25日平均、RSI、MACD、ボリンジャー、ローソク足、年初来高値/安値
- marginContext: 信用買残、信用売残、信用倍率、前週比、売建可否、逆日歩、株不足
- entryReadiness: direction、readiness、waitCondition、invalidation、stopReason
- shortUseCase: short_entry_candidate / buy_avoid_rebound_risk / short_term_event_short / exit_or_buy_avoid / not_short_side
- shortReadiness: high / medium / medium_low_liquidity / low_liquidity_avoid / avoid_short_rebound_risk / not_entry
- borrowContext: JPX貸借区分、売建可否、売り禁、逆日歩、証券会社在庫の確認状態

全部を毎回完璧に埋める必要はない。
ただし、`shortSignalRank: A/B`、`longSignalRank: A`、`negative_relative_strength` の銘柄は優先して埋める。
ショート候補は `shortSignalRank` だけで本文に出さず、`shortUseCase` と `shortReadiness` を添える。

## Investment Sector Pattern Policy
daily で新規シグナルや外部トリガーを記録する際は、可能な範囲で `sectorPattern.patternKey` を残す。

例:
- `sox_up__semiconductor_ai__earnings_revision__ma25_above`
- `rates_up__growth_saas__buyback_only__margin_buy_heavy`
- `oil_up__trading_resource__dividend_revision`
- `usd_jpy_up__machinery_export__upward_revision`

週次/月次整理で、この `patternKey` ごとに T+1 / T+5 / T+20 を集計する。

## Dividend Accumulation Timing Policy
配当目的の保有銘柄は日次ウォッチ対象にしないが、配当株の買い増し/新規打診に向きやすい地合いは通知対象にする。

通知する条件:
- 市場全体の急落やセクター売りで、配当株が材料なしに売られている
- 利回りが過去レンジやユーザー基準に対して魅力的になっている
- 業績、配当方針、配当性向、FCF、財務に明確な悪化が確認されていない
- 減配、下方修正、希薄化、営業CF悪化などの配当毀損シグナルが出ていない
- 権利落ち直後、決算前、地合い急変直後など、短期需給の歪みが説明できる

通知しない条件:
- 悪材料で売られている高利回り化
- 減配リスクが上がっただけの見かけ高配当
- 出来高が薄く、短期需給だけで価格が歪んでいる
- ユーザーの保有銘柄を毎日監視するだけの情報

daily 本文では、該当がある場合だけ「配当株の買い増し地合い」として短く通知する。
該当がなければ省略してよい。

### Daily Inbox Format
各 daily メモは次の形を基本にする。

```md
# YYYY-MM-DD Daily

## Topic
- slug: {{topic}}
- date: YYYY-MM-DD
- mode: collect-and-present

## Collected Items
### item_001: {{title}}
- source: {{source_label}}
- url: {{url}}
- collectedAt: {{iso_datetime}}
- summary: {{short_summary}}
- whyItMatters: {{reason_for_user}}
- status: new

## Investment Rule Notes
### signal_001: {{company_or_ticker}}
- ruleHits:
  - {{matched_signal_rule}}
- hypothesisOnly:
  - {{low_sample_rule}}
- sectorMarketContext:
  - proxyName: {{sector_proxy_name}}
  - proxyDirection: {{sector_tailwind_headwind_relative_strength_relative_weakness_neutral_unknown}}
  - relativeToTopixPct: {{relative_to_topix_pct_or_unknown}}
- rankAdjustmentReason:
  - {{why_rank_changed_or_not}}
- watchReason:
  - {{why_watch_or_skip}}
- ruleException:
  - {{unexpected_reaction_if_any}}
- ruleDashboard:
  - activeRule: {{active_rule_summary_or_none}}
  - watchRule: {{watch_rule_summary_or_none}}
  - hypothesisOnly: {{hypothesis_rule_summary_or_none}}
- tags:
  - {{tag_family_value}}

## Presentation Notes
- {{what_to_tell_user}}

## Unresolved Points
- {{unknown_or_unverified}}
```

## Constraints
- 今日時点の情報を扱う場合は、必ず最新確認を行う
- 収集した情報は本文を長く転載せず、要約とURLを保存する
- 投稿者名、個人アカウント名、連絡先などの個人情報は保存しない
- 自動大量クロールではなく、ユーザーの明示実行に対する調査メモとして保存する
- 投資情報は売買助言ではなく、材料整理と確認観点に限定する
- ポケモンカードは公式情報を最優先にする
- ポケモンカードは、抽選/再販/受注に加えて、新パック起点の環境デッキ変化も確認する
- ポケモンカードの環境デッキ変化がない場合は、確認したうえで `N/C` と表示する
- ポケモンカードの環境デッキ情報は、発売前予想と発売後実績を分けて扱う
- 技術記事は、流行度より学習価値と持ち帰れる設計・実装観点を優先する
- 技術記事セクションでは、各記事タイトルの直後に記事URLを必ず併記する
- 技術記事のURLを出典セクションだけにまとめて済ませない
- 技術記事の個別URLが未確認の場合は、一覧ページURLで代用せず「個別URL未確認」と明示する
- AIニュースは、発表の羅列ではなく実務への影響を含める
- `product-idea-watch` は通常の daily 本文には出さず、分析閾値に達したときだけ通知する
- `product-idea-watch` の裏収集は、daily 本文に載せない場合でも `inbox/` と `sources.json` には残す
- 未確認の情報は未確認として明示する
- 出典URLを付ける

## Output Contract
### proposal
- `date`
- `digest`
- `topic_sections`
- `sources`
- `unresolved_points`

### apply
- `created_files`
- `updated_files`
- `source_entries`
- `digest`
- `sources`
- `notes`

## Daily Output Shape
次の順で短く出す。

1. 全体要約
2. AI活用・ニュース
3. 投資
   - 外部トリガー
   - 市場地合い
   - セクター強弱
   - 重要開示/シグナル
   - 上昇シグナル候補: 3〜5件（不足時は確認済み `N/C`）
   - 下落シグナル候補: 3〜5件（不足時は確認済み `N/C`）
   - 再現ルール要約
- 売り/撤退/見送りシグナル
  - 空売り監視候補: `shortUseCase=short_entry_candidate` かつ `shortReadiness=high/medium`
  - 低流動性ショート注意: `shortUseCase=short_entry_candidate` かつ `shortReadiness=medium_low_liquidity/low_liquidity_avoid`
  - 戻り売り待ち: `shortReadiness=avoid_short_rebound_risk`
  - 買い回避/撤退候補: `exit_or_buy_avoid`
  - 短期イベント候補: `short_term_event_short`
  - 候補がない場合は確認済み `N/C`
   - 配当株の買い増し地合い
   - ウォッチリスト変化
4. ポケモンカード
   - 販売/抽選/再販
   - 新パック起点の環境デッキ変化。変化なしは `N/C`
5. 技術記事
   - 各記事は `タイトル - URL - なぜ読むか` の形で出す
6. ニーズ蓄積の通知
7. 出典
8. 次に見ること

`budget: lean` では、各セクションは原則1〜3行に圧縮する。
詳細な根拠や長い候補表は、必要ファイルへの参照だけに留める。

## Failure Handling
以下のいずれかで失敗を返す。

- `missing_daily_topics`
- `missing_canonical_file`
- `malformed_json`
- `insufficient_sources`
- `network_unavailable`

失敗時は以下を返す。

- `error_code`
- `message`
- `blocking_files`
- `suggested_action`

## Success Criteria
- ユーザーが今日見るべき情報を短時間で把握できる
- topic ごとの関心に沿っている
- 根拠URLがある
- 未確認事項が明示されている
- topic の `inbox/` と `sources.json` に当日分の情報蓄積が残っている
