# Command: investment-tag-index

## Purpose
`investment-research` の `signals` をもとに、軽量検索用の tag index を更新する。

この command は分析結果の補助索引を作るもので、売買助言ではない。

## Trigger
- 投資タグインデックス更新
- investment tag index
- tag-index refresh

## Required Inputs
- `date`
  - 指定がなければ現在日付を使う

## Optional Inputs
- `limit_days`
  - 対象日数
  - 指定がなければ 30 日
- `db`
  - 指定がなければ既定の investment DB を使う

## Read Scope
- `AGENT.md`
- `commands/investment-tag-index.md`
- `data/investment.db`

## Write Scope
- `topics/investment-research/tag-index.json`
- `topics/investment-research/tag-index.md`

## Execution Mode
- `apply`

## Output Contract
- `generatedAt`
- `itemCount`
- `tagCounts`
- `items`
- `byTag`

## Success Criteria
- signals の最新分から tag index が更新される
- JSON と Markdown の索引が揃う
- `investment-adaptive` などの後続処理が参照しやすい状態になる
