# Command: need-organize

## Purpose
`product-idea-watch` に蓄積された未整理ニーズを整理し、重複パターン、強いニーズ束、記事種、プロダクト種を抽出する。

## Trigger
- ニーズの整理
- ニーズ整理
- 不満の整理
- need organize
- product idea organize
- 記事ネタ整理
- ニーズトリアージ
- needs triage
- ニーズを分析

## Required Inputs
- `date`
  - 指定がなければ現在日付を使う

## Optional Inputs
- `unit`
  - 指定がなければ `unorganized`
  - `unorganized`
  - `pattern-analysis`
  - `article-seeds`
  - `product-seeds`
  - `all`
- `mode`
  - `proposal`
  - `apply`
- `source_ids`
- `max_items`

## Default Topic
- `topics/product-idea-watch`

## Read Scope
- `AGENT.md`
- `commands/need-organize.md`
- `commands/need-watch.md`
- `topics/product-idea-watch/topic-manifest.json`
- `topics/product-idea-watch/index.md`
- `topics/product-idea-watch/summary.md`
- `topics/product-idea-watch/decisions.md`
- `topics/product-idea-watch/tasks.json`
- `topics/product-idea-watch/sources.json`
- `topics/product-idea-watch/inbox/*`

## Write Scope
- `topics/product-idea-watch/summary.md`
- `topics/product-idea-watch/decisions.md`
- `topics/product-idea-watch/tasks.json`
- `topics/product-idea-watch/sources.json`
- 必要に応じて `topics/product-idea-watch/inbox/*analysis*.md`

## Execution Mode
- `proposal`
- `apply`

## Execution Units
### unorganized
`sources.json` の `status: new` の need-watch sources を読み、強い束、重複、分析候補を整理する。

### pattern-analysis
蓄積ニーズを次の観点で束ねる。

- pattern title
- cluster id
- evidence count
- source type count
- user segment
- pain severity
- paid alternative
- buildability
- opportunity score
- risks

cluster id は `commands/need-watch.md` の Cluster Policy を優先する。
既存 cluster に入るものは統合し、新しい束が見つかった場合だけ新規 cluster を提案する。

cluster の評価では次を分ける。

- `frequency`: どれだけ繰り返し出たか
- `sourceDiversity`: 独立した情報源やユーザー層の広さ
- `painCost`: 失敗時の金銭、時間、心理的コスト
- `currentWorkaround`: 既存代替が面倒か、高価か、不十分か
- `actionability`: 記事、チェックリスト、MVP、運用改善へ落とせるか
- `repoApplicability`: このRepo自身に適用できるか

### article-seeds
Noteなどの記事にできる題材を抽出する。

- title candidates
- main claim
- observed pattern
- why it matters
- outline
- source needs
- caution notes

### product-seeds
プロダクト案にできる題材を抽出する。

- target user
- job to be done
- current workaround
- proposed product
- MVP scope
- validation plan
- buildability

### all
全実行単位を行う。

## Constraints
- 投稿本文を長く転載しない
- 個人名、アカウント名、連絡先などの個人情報は保存しない
- 個別投稿を市場需要として断定しない
- 強いニーズは、件数だけでなく独立した source type の数で見る
- 記事化する場合も特定アプリ/個人を叩く形にしない

## Output Contract
### proposal
- `target_sources`
- `need_patterns`
- `article_seeds`
- `product_seeds`
- `source_status_updates`
- `unresolved_points`

### apply
- `updated_files`
- `created_files`
- `organized_source_ids`
- `cluster_updates`
- `pattern_count`
- `article_seed_count`
- `product_seed_count`
- `notes`

## Success Criteria
- 未整理ニーズが強いパターンへ束ねられる
- 記事種とプロダクト種が次に使える形で残る
- `summary.md` / `tasks.json` から次アクションが分かる

## Codex Triage Flow
日次運用は次の2段階を標準とする。

1. Python一次トリアージ（定期実行）
- `scripts/data/init_needs_db.py`
- `scripts/data/ingest_needs_db.py --date YYYY-MM-DD`
- `scripts/build_needs_ai_queue.py --limit 20`

2. Codex二次レビュー（手動実行）
- 入力: `prompts/needs-ai-queue.md` または `prompts/needs-ai-queue.json`
- 目的: 重複統合、優先度見直し、`watch/investigate/discard` の確定、根拠メモ整備
- 反映: `scripts/apply_needs_triage.py --input prompts/needs-ai-queue.json`

### Shortcut Prompt
`prompts/needs-triage.prompt.md` をCodexに貼って実行する。

合言葉 `ニーズを分析` が来た場合は、このショートカットを内部的に適用し、ユーザーに貼り付け作業を求めない。
