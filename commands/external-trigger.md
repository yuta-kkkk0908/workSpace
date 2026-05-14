# Command: external-trigger

## Purpose
米国要人発言、地政学、金利、為替、商品市況、米国株などの外部要因を収集し、日本株セクターと個別シグナルランクへの影響に翻訳する。

この command は売買助言ではなく、外部環境の読解、セクター影響の仮説、後日の検証ログを作るために使う。

## Trigger
- 外部要因
- external trigger
- 外部トリガー
- 米国要人発言
- 世界市場チェック
- 朝の市場要因
- 地政学リスク

## Required Inputs
- `date`
  - 指定がなければ現在日付を使う

## Optional Inputs
- `mode`
  - `collect`
  - `update-outcomes`
  - `collect-and-update`
- `focus`
  - `morning`
  - `us_officials`
  - `geopolitics`
  - `rates_fx`
  - `commodities`
  - `us_market`

## Default Topic
- `topics/investment-research`

## Read Scope
- `AGENT.md`
- `commands/external-trigger.md`
- `commands/daily.md`
- `commands/market-signal.md`
- `topics/investment-research/index.md`
- `topics/investment-research/summary.md`
- `topics/investment-research/decisions.md`
- `topics/investment-research/tasks.json`
- `topics/investment-research/sources.json`
- 必要に応じて `topics/investment-research/inbox/*external-triggers*.md`
- 必要に応じて `topics/investment-research/inbox/*daily*.md`

## Write Scope
- `topics/investment-research/inbox/YYYY-MM-DD-external-triggers.md`
- `topics/investment-research/sources.json`
- 必要に応じて `topics/investment-research/summary.md`
- 必要に応じて `topics/investment-research/decisions.md`
- 必要に応じて `topics/investment-research/tasks.json`

## Execution Mode
- `proposal`
- `apply`

## Collection Policy
一次情報を優先するが、初動検知では二次情報も使う。
二次情報で検知した場合は、市場データで反応確認し、可能な範囲で一次情報または信頼できる報道へ戻る。

優先ソース:
- FRB、FOMC、米財務省、米ホワイトハウス、日銀、財務省、JPXなどの一次情報
- Reuters、Bloomberg、日経、NHK、FNNなどの主要報道
- OANDA、Investing.com、TradingView、株探、トレーダーズWeb、Yahoo!ファイナンスなどの市場データ/市況

## External Trigger Types
- `us_official_statement`
  - 米大統領、FRB高官、財務長官、商務長官、USTR、要人発言
- `central_bank`
  - FOMC、日銀会合、議事要旨、政策金利、量的引き締め/緩和
- `macro_indicator`
  - CPI、PPI、雇用統計、GDP、ISM、PMI、小売売上高
- `geopolitics`
  - 戦争、停戦、軍事衝突、制裁、海峡封鎖、関税、外交交渉
- `fx_move`
  - ドル円急変、円買い介入観測、通貨当局発言
- `rates_move`
  - 米10年債、国内長期金利、金利急騰/急低下
- `commodity_move`
  - 原油、金、銅、天然ガス、穀物などの急変
- `us_market_move`
  - NYダウ、NASDAQ、S&P500、SOX、Magnificent 7、AI/半導体株の急変
- `accident_disaster`
  - 大規模災害、航空事故、港湾停止、停電、サイバー攻撃、リコール
- `policy_theme`
  - 防衛、原発、AI、電力、医療、通信、子育て/教育など政策テーマ

## Morning Workflow
朝の情報取得では、次の順で合理的に処理する。

1. ニュース検知
   - 米国要人発言、FRB高官発言、戦争/停戦、政策、関税、地政学、災害を確認する
   - 速報/二次情報でもよいが、未確認なら `verificationStatus: secondary_only` とする
2. 市場データ反応確認
   - NYダウ、NASDAQ、S&P500、SOX
   - 米10年債、ドル円、日経先物/CME、原油、金、必要に応じて銅
   - 反応がなければ、ニュースだけで過大評価しない
3. 日本株セクターへの翻訳
   - 半導体/AI/電子部品/グロース
   - 自動車/機械/輸出
   - 銀行/保険/不動産
   - 商社/海運/エネルギー/化学/空運
   - 防衛/電力/通信/医薬/食品/小売
4. ランク補正
   - `market-signal` の `externalContextAssessment` に反映する
   - 個別材料が同じでも、外部要因が追い風なら `longSignalRank` を上げやすく、逆風なら保守的にする
   - 追い風で上がらない銘柄は `negative_relative_strength`
   - 逆風で下がらない銘柄は `relative_strength`
5. 後日検証
   - T+0 / T+1 / T+5 で、外部要因が本当にセクターに効いたか確認する

## Sector Translation Rules
代表的な翻訳ルール:

- NASDAQ/SOX高
  - tailwind: 半導体、AI、電子部品、データセンター、グロース
  - watch: 高PERグロースの寄り天
- 米金利上昇
  - tailwind: 銀行、保険
  - headwind: グロース、不動産、REIT、高PER株
- 米金利低下
  - tailwind: グロース、不動産、REIT
  - headwind: 銀行の利ざや期待
- ドル円上昇 / 円安
  - tailwind: 自動車、機械、電子部品、輸出株
  - headwind: 輸入コストが重い食品、電力、空運、小売
- ドル円下落 / 円高
  - tailwind: 輸入コスト低下銘柄、内需の一部
  - headwind: 自動車、機械、電子部品、輸出株
- 原油高
  - tailwind: エネルギー、資源、商社、防衛の一部
  - headwind: 空運、化学、電力、陸運、消費
- 原油安
  - tailwind: 空運、化学、電力、消費
  - headwind: 資源、エネルギー、商社の一部
- 戦争/地政学緊張
  - tailwind: 防衛、エネルギー、金、資源
  - headwind: 空運、旅行、消費、海運は内容次第
- 停戦/緊張緩和
  - tailwind: リスクオン、空運、旅行、消費、半導体/AI
  - headwind: 防衛、資源、原油高メリット銘柄の一部
- 関税/貿易摩擦
  - headwind: 自動車、機械、輸出、商社、海運
  - tailwind: 国内代替、内需、防衛/政策テーマは内容次第

## Log Format
`topics/investment-research/inbox/YYYY-MM-DD-external-triggers.md` に保存する。

```md
# YYYY-MM-DD External Triggers

## Topic
- slug: investment-research
- date: YYYY-MM-DD
- mode: collect-and-update

## Market Snapshot
- collectedAt: {{iso_datetime}}
- usMarket:
  - dow: {{value_change_or_unknown}}
  - nasdaq: {{value_change_or_unknown}}
  - sp500: {{value_change_or_unknown}}
  - sox: {{value_change_or_unknown}}
- futures:
  - nikkeiFutures: {{value_change_or_unknown}}
  - cmeNikkei: {{value_change_or_unknown}}
- fxRates:
  - usdJpy: {{value_or_unknown}}
- rates:
  - us10y: {{value_change_or_unknown}}
  - jp10y: {{value_change_or_unknown}}
- commodities:
  - wti: {{value_change_or_unknown}}
  - gold: {{value_change_or_unknown}}
  - copper: {{value_change_or_unknown}}

## External Triggers
### trigger_YYYYMMDD_001: {{title}}
- triggerType: us_official_statement / central_bank / macro_indicator / geopolitics / fx_move / rates_move / commodity_move / us_market_move / accident_disaster / policy_theme
- source: {{source_label}}
- url: {{source_url}}
- sourceType: primary / secondary / market_data
- verificationStatus: primary_confirmed / secondary_confirmed / secondary_only / market_reaction_only / unconfirmed
- publishedAt: {{iso_datetime_or_unknown}}
- eventSummary: {{short_summary}}
- keyActor: {{person_or_institution_or_unknown}}
- marketReaction:
  - usMarket: {{reaction}}
  - futures: {{reaction}}
  - fx: {{reaction}}
  - rates: {{reaction}}
  - commodities: {{reaction}}
- affectedSectors:
  - sector: {{sector}}
    impact: tailwind / headwind / mixed / neutral / unknown
    reason: {{why}}
- japanMarketHypothesis: {{expected_japan_market_impact}}
- watchUse:
  - market_context
  - sector_rotation
  - rank_adjustment
  - dividend_accumulation_timing
- rankImpact:
  - longBias: upgrade / downgrade / keep / hold
  - shortBias: upgrade / downgrade / keep / hold
  - reason: {{rank_impact_reason}}
- checkLater:
  - T+0:
  - T+1:
  - T+5:
- outcome:
  - T+0:
  - T+1:
  - T+5:
- lesson:
```

## Constraints
- 売買推奨はしない
- ニュースの見出しだけで断定しない
- 可能な限り市場データ反応を確認する
- 二次情報だけの場合は `secondary_only` と明示する
- 個人アカウントの投稿本文、個人情報、長文引用は保存しない
- 外部要因を過大評価せず、反応がなければ `marketReaction: muted` とする
- 日本株セクターへの影響は仮説として保存し、後日 T+0 / T+1 / T+5 で検証する

## Output Contract
### proposal
- `date`
- `market_snapshot`
- `external_triggers_to_log`
- `sector_impacts`
- `rank_adjustments`
- `unresolved_points`

### apply
- `created_files`
- `updated_files`
- `source_entries`
- `logged_trigger_count`
- `sector_impacts`
- `rank_adjustments`
- `notes`

## Success Criteria
- ニュース、要人発言、市場データ反応、日本株セクター影響が同じログに残る
- market-signal の rank 補正に使える
- 後から「外部要因が本当に効いたか」を検証できる
