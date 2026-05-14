# Command: market-signal

## Purpose
日本株の一次情報シグナルを収集し、発生時の仮説と、その後の株価反応を蓄積して、シグナルの読み方を学習する。

この command は売買助言ではなく、情報読解と検証ログの作成を目的とする。
銘柄情報の取得は、デイトレ/スイングで使う短期材料の読解にも使う。

## Trigger
- 市場シグナル
- market signal
- シグナル収集
- 開示読解
- TDnet読解
- 投資シグナル検証

## Required Inputs
- `date`
  - 指定がなければ現在日付を使う

## Optional Inputs
- `mode`
  - `collect`
  - `update-outcomes`
  - `collect-and-update`
- `universe`
  - `watchlist`
  - `high-dividend`
  - `all`
- `signal_types`
  - `dividend_revision`
  - `earnings_revision`
  - `buyback`
  - `tob`
  - `capital_policy`
  - `midterm_plan`
  - `large_holding`
  - `macro_policy`
  - `downward_revision`
  - `dividend_cut`
  - `dilution`
  - `impairment_loss`
  - `negative_cashflow`
  - `weak_guidance`
  - `sell_the_news`
  - `technical_breakdown`

## Default Topic
- `topics/investment-research`

## Read Scope
- `AGENT.md`
- `commands/market-signal.md`
- `topics/investment-research/index.md`
- `topics/investment-research/summary.md`
- `topics/investment-research/decisions.md`
- `topics/investment-research/signal-rules.md`
- `topics/investment-research/tasks.json`
- `topics/investment-research/sources.json`
- 必要に応じて `topics/investment-research/inbox/*market-signals*.md`

## Write Scope
- `topics/investment-research/inbox/*market-signals*.md`
- `topics/investment-research/sources.json`
- 必要に応じて `topics/investment-research/summary.md`
- 必要に応じて `topics/investment-research/decisions.md`
- 必要に応じて `topics/investment-research/tasks.json`

## Execution Mode
- `proposal`
- `apply`

## Collection Policy
一次情報を優先する。

優先ソース:
- TDnet
- 企業IR
- EDINET
- 日銀
- JPX
- 財務省、経産省、総務省など公的機関

補助ソース:
- 株探、みんかぶ、Yahoo!ファイナンスなどの二次情報
- 補助ソースを使った場合は、可能な限り一次情報へ戻る

## Disclosure Coverage Policy
TDnet/企業IRの適時開示は、自社株買いだけに寄せない。
自社株買いは検出しやすく、短期需給に効くことがあるため重要だが、株価材料としては一部にすぎない。

daily / backtest / market-signal では、次の順で「株価に効きそうか」ではなく「検証すべき材料か」を広く拾う。

1. 業績・決算
   - 決算短信、四半期決算、通期決算
   - 業績予想修正、上方修正、下方修正
   - 進捗率、コンセンサス乖離、ガイダンス
   - セグメント別の急変、受注、粗利率、販管費、営業CF
2. 配当・株主還元
   - 増配、減配、無配、記念配当、特別配当
   - DOE、累進配当、配当方針変更
   - 自社株買い、自己株式消却、自社株TOB
3. 資本政策・希薄化
   - 公募増資、第三者割当、新株予約権、CB
   - 株式分割、株式併合、優待新設/廃止
   - 親子上場解消、MBO、TOB、上場廃止、指定替え
4. 事業イベント
   - 大型受注、契約締結、提携、M&A、事業譲渡、撤退
   - 新製品、承認取得、薬事/特許、設備投資
   - 月次売上、KPI、ユーザー数、既存店売上
5. リスク・不祥事
   - 特別損失、減損、訴訟、行政処分、リコール
   - 決算遅延、監査法人変更、内部統制、粉飾疑義
   - 災害、事故、サイバー攻撃、操業停止
6. 外部・制度要因
   - 政策、規制、補助金、関税、金利、為替、資源価格
   - 米国市場、SOX、NASDAQ、要人発言、地政学
   - セクター全体に効くニュース

各シグナルには、できるだけ `disclosureCategory` と `materialityReason` を残す。
強い材料だけでなく、「市場が反応しなかった材料」「悪材料なのに下がらなかった材料」も学習価値が高いため保存する。

## Signal Types
初期対象は次のシグナルを広く扱う。

- 配当予想修正
- 増配、減配、記念配当、特別配当
- 業績予想修正
- 自社株買い
- TOB、MBO
- 株主還元方針、DOE、累進配当
- 中期経営計画
- 大量保有、保有割合変化
- 日銀、金利、為替、政策変更

下落・売り方向の初期対象:

- 下方修正
- 減配、無配転落
- 公募増資、第三者割当、希薄化
- 特別損失、減損
- 営業CF悪化、利益は出ているが現金が出ていない
- 弱いガイダンス、コンセンサス未達
- 自社株買い中止、還元方針後退
- 決算遅延、監査法人変更
- 大株主売却、大量保有減少
- 不祥事、行政処分、リコール
- 好材料なのに上がらない、寄り天、出来高急増の陰線
- 移動平均割れ、MACDデッドクロス、ボリンジャーバンド反落などの technical breakdown

## Market Reaction Windows
株価反応は次の窓で記録する。

- `T+0`: 当日終値
- `T+1`: 翌営業日終値
- `T+5`: 約1週間後
- `T+20`: 約1か月後

デイトレ/スイング用途では、特に `T+0`、`T+1`、`T+5` を重視する。
`T+20` は短期材料が中期テーマ化したか、または失速したかの確認に使う。

発表時刻に応じて `session` を必ず記録する。

- `before_open`
- `intraday`
- `after_close`
- `holiday`
- `unknown`

## Direction Classification Policy
`expectedDirection: up` は安易に使わない。
好材料に見える開示でも、短期反応は事前期待、決算内容、発表時刻、地合い、流動性、既に場中で織り込まれたかで大きく変わる。

### External Context First
ランク付けの前に、必ず米国市場、世界市場、為替、金利、商品市況を確認する。
個別開示の強弱だけで `longSignalRank` / `shortSignalRank` を決めない。

最低限確認するもの:

- 米国株: NYダウ、NASDAQ、S&P500、SOX指数
- 日本関連: 日経先物、CME日経平均先物、ドル円
- 金利: 米10年債利回り、国内長期金利
- 商品: 原油、金、必要に応じて銅など景気敏感商品
- リスク要因: 地政学、政策発言、中央銀行、関税、規制、災害、大型事故

外部環境は次のようにランクへ反映する。

- 個別好材料 + 外部環境追い風 + セクター追い風: `longSignalRank` を上げやすい
- 個別好材料 + 外部環境逆風: `longSignalRank` を保守的にし、T+0/T+1の相対強度を見る
- 個別好材料なのに、外部環境追い風で下落: `negative_relative_strength` として `shortSignalRank` を検討する
- 個別悪材料 + 外部環境逆風: `shortSignalRank` を上げやすい
- 個別悪材料でも、外部環境逆風の中で下がらない: 売り候補化せず、相対強度を記録する
- 外部環境だけで動いた可能性が高い場合: 個別シグナルの評価を過度に下げず、`external_context_driven` として分離する

Rank C になった銘柄は、必ず「個別材料が弱い」のか「外部環境に負けた」のかを `rankAdjustmentReason` に残す。

### Up 判定を許可しやすい条件
次の複数が同時に揃う場合だけ `expectedDirection: up` を検討する。

- 上方修正、最高益見通し、増配、自社株買い、消却、株式分割など複数の好材料が重なる
- 業績見通しが明確に強く、売上/利益/ガイダンスの質も悪くない
- 増配や自社株買いが一過性ではなく、還元方針や財務余力と整合している
- 発表が `after_close` または `before_open` で、まだ場中に織り込まれていない
- 直前株価が過熱しすぎておらず、材料出尽くしになりにくい
- 市場地合い、セクター地合い、出来高の条件が追い風

### Neutral / unclear を優先する条件
次のいずれかがある場合は、原則 `neutral` または `unclear` を優先する。

- 自社株買い単体
- 自社株買い + 消却でも、決算内容やガイダンスが弱い
- 増配があるが、同時に減益、下方修正、売上下方、弱い見通しがある
- 場中発表で既に急騰している
- 直近で大きく上昇済みで、好材料が織り込まれている可能性が高い
- 大型株で材料規模が時価総額に対して小さい
- コンセンサス比、進捗率、配当性向、FCF、財務余力が未確認

### Sell the news / relative weakness
好材料にもかかわらず次の条件が出た場合は、`sell_the_news` または `negative_relative_strength` として記録する。

- 強い地合いの中で対象銘柄だけ下落する
- 寄り付きは高いが、引けにかけて失速する
- 出来高急増を伴って陰線になる
- 好材料なのに前日終値を維持できない
- 同業/指数に対して明確に弱い

この場合、`expectedDirection` は後から見て外れたことを責めるためではなく、「何を過大評価したか」を残すために使う。
`relativeStrength` には、指数/セクターと比べた強弱を必ず記録する。

## Required Recording Fields
日次のシグナル記録では、次を必須項目とする。

- `hypothesisDirection.primary`（up/down/neutral/unclear）
- `hypothesisDirection.rationaleTags`（最低2タグ）
- `checkLater.T+1 / T+5 / T+20`
- `outcome.T+1 / T+5 / T+20`（期限到来時に更新）
- `requiredCheck.gateStatus`
- `requiredCheck.materialSignalChecked / technicalSignalChecked / externalContextChecked`

判定ルール:
- 材料、テクニカル、外部要因のうち2系統以上を確認できない場合は `gateStatus: fail` とし、`expectedDirection` は `neutral` または `unclear` を優先する。

## Provisional Signal Rules Policy
`topics/investment-research/signal-rules.md` が存在する場合は、シグナル収集・ランク付け・outcome 更新の前に読む。

暫定ルールの使い方:

- 該当する組み合わせを `ruleHits` に残す
- ランク補正した理由を `rankAdjustmentReason` に残す
- 見送り/監視/撤退に使った観点を `watchReason` に残す
- 暫定ルールと逆の反応が出た場合は `ruleException` または `lessonCandidate` として残す
- n<4 の組み合わせは `hypothesis_only` として扱い、強いランク根拠にしない

特に確認する軸:

- disclosureCategory / signalType
- externalContext / marketContext
- sectorPattern / sectorProfile
- sectorMarketContext / sector proxy relative strength
- marginContext / marginBucket
- volumeContext / volumeRatioBucket
- technicalContext / T+1Candle / upper_wick / bullish_close
- session / after_close / intraday

暫定ルールは売買助言ではなく、監視優先度、見送り理由、検証ログの粒度を揃えるために使う。

## Signal Rank Policy
シグナルは短期方向予想だけで評価しない。
信用買い/信用売りの監視に使うため、上昇シグナルと下降シグナルを分けて評価する。
`longSignalRank` は信用買い/買い候補としての強さ、`shortSignalRank` は信用売り/買い回避/利確候補としての強さを表す。
`expectedDirection` は短期株価方向、`candidateUse` は用途として分ける。

### Long Rank A: long_candidate / investment_candidate
信用買い、買い候補、投資候補として強監視に値する。

- 上方修正 + 増配
- 最高益見通し + 増配
- 累進配当、DOE、配当方針強化
- 自社株買い + 消却 + 業績堅調
- 中期経営計画で還元方針強化
- 好決算後も高値維持
- 地合い悪でも下がらない
- ファンダ好材料 + テクニカル好形状が一致
- 信用売り残が多い状態で上抜けし、踏み上げ余地がある

### Long Rank B: long_watch
買い監視対象として残すが、単体では買い候補にしない。

- 自社株買い単体
- 増配単体
- 月次好調
- 大型受注
- セクター追い風
- 出来高急増
- 年初来高値更新
- テクニカル好形状のみ

### Long Rank C: avoid_long / take_profit_watch
買い回避、利確、弱さ確認に使う。

- 下方修正
- 減配
- 希薄化
- 弱いガイダンス
- 好材料後の寄り天
- 強地合いで下落
- 増配だが減益
- 自社株買いでも売られる
- テクニカル悪化が明確

### Short Rank A: short_candidate
信用売り候補として強監視に値する。

- 下方修正 + 減配
- 希薄化 + 弱いガイダンス
- 決算遅延、監査法人変更、不祥事、行政処分
- 強地合いで大陰線
- 高値圏から出来高急増で崩れる
- 25MA/75MA割れ + 悪材料
- 好材料なのに寄り天大陰線
- 信用買い残が重い状態で崩れる

### Short Rank B: short_watch / hedge_watch
信用売り監視、ヘッジ、買い回避に使う。

- 自社株買いでも強地合いで下落
- 消却付きでも売られる
- 好材料後に上値が重い
- MA25割れ、出来高増の陰線
- 弱いガイダンス単体
- セクター逆風 + 相対弱い

### Short Rank C: avoid_long
買い回避の材料だが、信用売り候補としては弱い。

- 混在材料で評価が割れる
- 流動性が薄い
- 下落幅が小さい
- 踏み上げリスクが高い
- テクニカル悪化が未確認

`longSignalRank: C` は「買いには向かない」を意味するだけで、`shortSignalRank: A` と同義ではない。
信用売り候補にするには、下落材料、テクニカル悪化、流動性、信用需給、逆行リスクを別途確認する。

### Technical Signal Policy
短期売買向けには、ファンダメンタルズとは別にテクニカルシグナルを記録する。

初期対象:

- `ma25_bounce`
- `ma75_bounce`
- `ma25_breakout`
- `ma25_breakdown`
- `large_bullish_candle_volume`
- `large_bearish_candle_volume`
- `gap_up_hold`
- `gap_down_rebound`
- `high_breakout_volume`
- `upper_shadow_after_high`
- `macd_dead_cross`
- `bollinger_plus2_reversal`
- `bollinger_minus2_rebound`

`signalSource` は `fundamental` / `technical` / `mixed` のいずれかにする。
短期の優先候補は `mixed` を重視する。
テクニカル情報が未確認の場合は、無理に推測せず `technicalSignal: unconfirmed` とする。

### Technical Context Policy
テクニカルは全指標を網羅しない。
短期Rank補正に効くものだけ、毎回同じ粒度で確認する。

優先確認:

- 移動平均: MA5 / MA25 / MA75
- 出来高: 当日出来高、5日平均、25日平均、出来高倍率
- RSI: 30未満、50前後、70超、80超
- MACD: ゴールデンクロス、デッドクロス、ゼロライン上下
- ボリンジャーバンド: +2σ反落、-2σ反発、バンドウォーク
- ローソク足: 大陽線、大陰線、上ヒゲ、下ヒゲ、包み足、十字線
- 位置: 年初来高値/安値、直近高値/安値、ギャップ、窓埋め

Rankへの使い方:

- 好材料 + MA25上 + 出来高2倍以上 + 陽線引け: `longSignalRank` を上げやすい
- 好材料 + 寄り天 + 上ヒゲ + 出来高急増: `sell_the_news` として `longSignalRank` を下げる
- 悪材料 + MA25割れ + 出来高2倍以上 + 大陰線: `shortSignalRank` を上げやすい
- 強地合い + MA25割れ + 年初来安値: `negative_relative_strength` として重視する
- 弱地合い + MA25上維持 + 下ヒゲ: `relative_strength` として重視する
- RSI80超、+2σ反落、急騰後出来高減少: 新規追随ではなく `take_profit_watch`

テクニカルは「売買サイン」ではなく、ファンダ/外部環境Rankを補正する材料として扱う。

### Margin And Lending Policy
信用残・貸借は、特に `shortSignalRank` と踏み上げリスクの判定に使う。

優先確認:

- 信用買残
- 信用売残
- 信用倍率
- 前週比
- 売建可否
- 貸借銘柄か
- 逆日歩
- 株不足
- 日証金残が確認できる場合は速報性を優先

Rankへの使い方:

- 信用買残が多い + 悪材料 + MA割れ: `shortSignalRank` を上げやすい
- 信用買残が増加 + 株価下落: 戻り売り/上値重さとして記録
- 信用売残が多い + 好材料 + 高値上抜け: 踏み上げ余地として `longSignalRank` を上げやすい
- 逆日歩/株不足/売禁懸念: `shortSignalRank` を下げ、`shortSqueezeRisk` を上げる
- 低流動性 + 信用情報未確認: short A にしない

信用残は週次データで遅れるため、短期判断では出来高・ローソク足・日証金速報があれば併用する。

### Entry Readiness Policy
Rankは監視優先度であり、実際に入れる状態かどうかとは分ける。
売買助言ではなく、検証用の準備度として `entryReadiness` を記録する。

`entryReadiness.readiness`:

- `high`: 材料、外部環境、セクター、テクニカル、需給が概ね同方向
- `medium`: 材料はあるが、確認待ちまたは一部逆風
- `low`: Rankはあるが、寄り付き過熱、低流動性、需給不明、逆行リスクが大きい
- `avoid`: 見送り条件が明確
- `unknown`: 必要情報が不足

確認する観点:

- direction: long / short / avoid / watch
- trigger: 何がエントリー仮説の中心か
- waitCondition: 何を待つか
- invalidation: どの条件で仮説を取り下げるか
- stopReason: 見送り理由
- timeHorizon: intraday / swing / position

例:

- long readiness high:
  - 複合好材料
  - 外部環境追い風
  - セクター追い風
  - MA25上
  - 出来高増
  - 引け強い
- short readiness high:
  - 悪材料
  - 外部環境逆風
  - MA25割れ
  - 出来高増大陰線
  - 信用買残が重い
- avoid:
  - 寄り付きで上げすぎ
  - 出来高が続かない
  - 前場高値を超えない
  - 低流動性
  - 信用需給が危険
  - 決算内容が未確認

### Time Of Day Policy
同じ材料でも、朝、前場、後場、引け後で意味が変わる。
記録では `timeOfDayPlan` と `sessionRead` を分ける。

朝 / before_open:

- 外部トリガー、米国市場、SOX、金利、ドル円、原油、日経先物を確認
- 寄り前注目セクターを仮説化
- ギャップアップ/ギャップダウンしそうな銘柄を確認
- 寄りで飛びつくより、寄り後の維持を確認する条件を置く

前場 / morning_session:

- 寄り付きギャップが維持されるか
- 寄り天/寄り底か
- 出来高が前日/5日平均に対して増えているか
- 外部トリガーのセクター仮説と実際の値動きが一致するか

後場 / afternoon_session:

- 前場の高値/安値を更新するか
- 引けに向けた買い/売りが出るか
- 日計りではなくスイングに残せる強さがあるか

引け後 / after_close:

- 適時開示、決算、IRを確認
- 翌営業日の仮説を作る
- T+0/T+1/T+5/T+20の更新対象を整理する

### T+20 Swing Outcome Policy
T+20は毎日細かく追わず、週次または期限到来時に確認する。
目的は、短期材料が中期テーマ化したか、材料出尽くしだったかを判定すること。

確認する観点:

- T+1/T+5の高値をT+20までに超えたか
- MA25を維持したか
- 出来高が継続したか
- セクター地合いが続いたか
- 外部トリガーが継続テーマ化したか
- 初動から全戻ししたか
- 増配/還元材料が配当株評価として残ったか

`swingOutcome`:

- `trend_continuation`: T+20まで強さ継続
- `initial_pop_only`: 初動だけ
- `failed_breakout`: 上抜け失敗
- `mean_reversion`: 全戻し/平均回帰
- `theme_continuation`: テーマ化
- `external_context_driven`: 外部環境で説明できる
- `unknown`: 未確認

### Sector Pattern Policy
セクターごとの勝ちパターンは、個別シグナルのたびに軽くタグ付けして後で集計する。
最初から統計的有意性を求めず、同じ形式で蓄積することを優先する。

優先セクター:

- semiconductor_ai
- growth_saas
- trading_resource
- bank_insurance
- machinery_export
- auto_export
- food_defensive
- real_estate_reit
- shipping_logistics
- defense_power
- telecom
- retail_consumer

記録する軸:

- externalTriggerType
- sector
- signalType
- technicalPattern
- marginPattern
- sectorMarketContext
- longSignalRank
- shortSignalRank
- entryReadiness
- T+1 result
- T+5 result
- T+20 result
- missFactor

例:

- NASDAQ/SOX高 + 半導体好決算 + MA25上 + 出来高増
- 米金利上昇 + グロース自社株買い単体 + 信用買残重い
- 原油高 + 商社増配 + 資源価格上昇
- 円安 + 機械上方修正 + 年初来高値更新

## Signal Log Format
`topics/investment-research/inbox/YYYY-MM-DD-market-signals.md` に保存する。

```md
# YYYY-MM-DD Market Signals

## Topic
- slug: investment-research
- date: YYYY-MM-DD
- mode: collect-and-update

## Signals
### signal_YYYYMMDD_001: {{company}} {{signal_title}}
- ticker: {{ticker}}
- company: {{company}}
- source: {{source_label}}
- url: {{source_url}}
- publishedAt: {{iso_datetime_or_unknown}}
- session: before_open / intraday / after_close / holiday / unknown
- signalType: dividend_revision / earnings_revision / buyback / tob / capital_policy / midterm_plan / large_holding / macro_policy
- signalRank: A / B / C
- longSignalRank: A / B / C / none
- shortSignalRank: A / B / C / none
- signalSource: fundamental / technical / mixed
- candidateUse: investment_candidate / watch_candidate / avoid_candidate / take_profit_watch
- signalSummary: {{short_summary}}
- expectedDirection: up / down / neutral / unclear
- tradeUse: buy_candidate / avoid_buy / take_profit_watch / short_candidate / hedge_watch / watch_only
- tradeHorizon: intraday / swing / position / dividend_research / unknown
- confidence: 1-5
- reason: {{why}}
- priceAction:
  - openReaction: {{gap_up_gap_down_or_unknown}}
  - intradayShape: {{trend_or_yoriten_or_unknown}}
  - closeStrength: {{strong_weak_or_unknown}}
  - volumeSpike: {{yes_no_unknown}}
  - relativeStrength: {{strong_vs_market_weak_vs_market_or_unknown}}
- technicalSignal:
  - type: {{technical_signal_or_unconfirmed}}
  - trend: uptrend / downtrend / range / unknown
  - volume: high / normal / low / unknown
  - candle: bullish / bearish / doji / upper_shadow / lower_shadow / unknown
  - maPosition: above_25ma / below_25ma / around_25ma / unknown
- technicalContext:
  - ma5: {{price_relation_or_unknown}}
  - ma25: {{price_relation_or_unknown}}
  - ma75: {{price_relation_or_unknown}}
  - volumeToday: {{value_or_unknown}}
  - volumeAvg5: {{value_or_unknown}}
  - volumeAvg25: {{value_or_unknown}}
  - volumeRatio5: {{ratio_or_unknown}}
  - rsi: {{value_zone_or_unknown}}
  - macd: golden_cross / dead_cross / above_zero / below_zero / neutral / unknown
  - bollinger: plus2_touch / plus2_reversal / minus2_touch / minus2_rebound / band_walk / neutral / unknown
  - candleDetail: large_bullish / large_bearish / upper_shadow / lower_shadow / doji / gap_up / gap_down / unknown
  - highLowContext: year_high / year_low / recent_high_break / recent_low_break / range / unknown
- marginContext:
  - marginBuyBalance: high / normal / low / unknown
  - marginSellBalance: high / normal / low / unknown
  - marginRatio: {{margin_ratio_or_unknown}}
  - marginBuyChange: increasing / decreasing / flat / unknown
  - marginSellChange: increasing / decreasing / flat / unknown
  - lendable: yes / no / unknown
  - reverseDailyFee: yes / no / unknown
  - stockShortage: yes / no / unknown
  - shortSqueezeRisk: low / medium / high / unknown
  - sellPressureRisk: low / medium / high / unknown
- marketContext:
  - indexTrend: {{nikkei_topix_growth_context}}
  - globalMarket: {{us_global_market_context}}
  - futures: {{nikkei_futures_cme_context}}
  - fxRates: {{usd_jpy_and_relevant_fx_context}}
  - rates: {{us_japan_rates_context}}
  - commodities: {{oil_gold_copper_context}}
  - sectorTrend: {{sector_context}}
  - volumeContext: {{volume_or_turnover_context}}
  - externalFactors: {{fx_rates_policy_us_market_context}}
- externalContextAssessment:
  - directionBias: tailwind / headwind / mixed / neutral / unknown
  - affectedSectors:
    - {{sector}}
  - rankImpact: upgrade / downgrade / keep / hold_for_confirmation / unknown
  - rankAdjustmentReason: {{whether_rank_reflects_company_signal_or_external_context}}
- ruleContext:
  - ruleVersion: {{signal_rules_version_or_date}}
  - ruleHits:
    - {{matched_rule_name_or_condition}}
  - hypothesisOnly:
    - {{n_less_than_4_or_low_confidence_rule}}
  - rankAdjustmentReason:
    - {{why_rank_was_adjusted_by_rule}}
  - watchReason:
    - {{why_this_is_watch_long_short_avoid_or_follow_up}}
  - ruleException:
    - {{if_price_action_contradicts_rule}}
  - lessonCandidate:
    - {{what_to_verify_at_T1_T5_T20}}
- sectorPattern:
  - sector: {{sector_key}}
  - externalTriggerType: {{external_trigger_type_or_none}}
  - sectorImpact: tailwind / headwind / mixed / neutral / unknown
  - patternKey: {{external_trigger_plus_sector_plus_signal_type}}
  - comparablePastSignals:
    - {{past_signal_id_or_none}}
- sectorMarketContext:
  - proxySymbol: {{sector_proxy_symbol}}
  - proxyName: {{sector_proxy_name}}
  - proxyDirection: sector_tailwind / sector_headwind / sector_relative_strength / sector_relative_weakness / sector_positive_but_market_like / sector_negative_but_market_like / sector_neutral_or_unclear / unknown
  - proxyPct: {{sector_proxy_pct_or_unknown}}
  - topixPct: {{topix_proxy_pct_or_unknown}}
  - relativeToTopixPct: {{relative_to_topix_pct_or_unknown}}
  - sectorRead: {{how_sector_context_changes_rank_or_watch_reason}}
- timeOfDayPlan:
  - beforeOpen: {{what_to_check_before_open}}
  - morningSession: {{what_to_check_in_morning}}
  - afternoonSession: {{what_to_check_in_afternoon}}
  - afterClose: {{what_to_check_after_close}}
- sessionRead:
  - morning: {{gap_and_first_hour_read_or_unknown}}
  - afternoon: {{continuation_or_reversal_or_unknown}}
  - close: {{close_read_or_unknown}}
- entryReadiness:
  - direction: long / short / avoid / watch / unknown
  - readiness: high / medium / low / avoid / unknown
  - trigger: {{main_trigger}}
  - waitCondition: {{what_to_wait_for}}
  - invalidation: {{what_invalidates_the_setup}}
  - stopReason:
    - {{reason_to_not_enter}}
  - timeHorizon: intraday / swing / position / unknown
- riskFactors:
  - {{risk}}
- skipReasons:
  - {{reason_to_avoid_or_wait}}
- directionQuality:
  - upAllowedByRule: yes / no / unclear
  - neutralOrUnclearReason: {{why_not_up_if_any}}
  - sellTheNewsRisk: low / medium / high / unknown
- revisedAssessment:
  - ruleVersion: {{rule_version}}
  - originalExpectedDirection: {{original_expected_direction}}
  - revisedExpectedDirection: {{revised_expected_direction}}
  - revisedSignalRank: {{revised_signal_rank}}
  - revisedLongSignalRank: {{revised_long_signal_rank}}
  - revisedShortSignalRank: {{revised_short_signal_rank}}
  - missFactors:
    - {{miss_factor}}
- checkLater:
  - T+1:
  - T+5:
  - T+20:
- outcome:
  - T+0:
  - T+1:
  - T+5:
  - T+20:
- swingOutcome:
  - outcomeType: trend_continuation / initial_pop_only / failed_breakout / mean_reversion / theme_continuation / external_context_driven / unknown
  - ma25Maintained: yes / no / unknown
  - volumeContinuation: yes / no / unknown
  - t20ExceededInitialHigh: yes / no / unknown
  - lessonForNextSignal: {{lesson}}
- lesson:
```

## Outcome Update Policy
daily 実行時または market-signal 実行時に、過去の open signals を確認し、期限が来たものだけ `outcome` と `lesson` を追記する。

更新対象:
- T+1 が未記入で、翌営業日以降になった signal
- T+5 が未記入で、5営業日程度経過した signal
- T+20 が未記入で、20営業日程度経過した signal

## Constraints
- 売買推奨はしない
- 短期トレードの確実性を断定しない
- デイトレ/スイング用途のシグナルでも、売買指示ではなく、発生時仮説と後日検証として記録する
- 発表時刻、寄り付き反応、出来高、寄り天/引け強弱を、可能な範囲で必ず分けて記録する
- 売り/空売りは買いよりリスク構造が厳しいため、最初は `avoid_buy` / `take_profit_watch` / `hedge_watch` としての利用を優先する
- `short_candidate` は、明確な下落シグナル、流動性、逆行リスク、需給、規制を確認できる場合だけ記録する
- 二次情報だけで確定扱いしない
- 価格反応は地合い、流動性、織り込み、決算期待と分けて考える
- `expectedDirection: up` は厳格に使い、自社株買い単体や場中反応済み材料は `neutral` / `unclear` を優先する
- 強地合いで下落した銘柄は、材料が好材料でも `negative_relative_strength` として扱う
- 好材料後の寄り天、失速、出来高急増陰線は `sell_the_news` 候補として記録する
- `signal-rules.md` に該当する場合は `ruleContext.ruleHits` を残し、該当してもn<4なら `hypothesisOnly` に入れる
- セクターproxyを確認できる場合は `sectorMarketContext` を残し、市場全体の地合いと分けて読む
- 自分の第一印象と後日の結果を分けて記録する
- 結果が外れた場合ほど `lesson` を残す

## Output Contract
### proposal
- `date`
- `signals_to_log`
- `outcomes_to_update`
- `unresolved_points`

### apply
- `created_files`
- `updated_files`
- `source_entries`
- `logged_signal_count`
- `updated_outcome_count`
- `notes`

## Success Criteria
- 一次情報シグナルと予想、結果、学びが同じログに残る
- 後から同種シグナルの傾向を比較できる
- 売買判断ではなく読解力向上に使える
