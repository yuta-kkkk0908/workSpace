# Command: daily

## Purpose
ユーザーが「今日の情報」と依頼したときに、daily watch 対象の topic から当日見るべき情報を収集・整理し、短く解説する。

## Trigger
- 今日の情報
- 今日のまとめ
- daily
- daily digest
- 今日見るべき情報

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
- `topics/*/topic-manifest.json`
- `topics/{{topic}}/index.md`
- `topics/{{topic}}/summary.md`
- `topics/{{topic}}/decisions.md`
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

## Execution Mode
- `proposal`
- `apply`

## Default Behavior
`daily` は、ユーザーが明示的に `present-only` を指定しない限り `collect-and-present` で実行する。

毎回の daily で、確認した情報は topic ごとに短い収集メモとして `inbox/` に保存し、`sources.json` に参照を追加する。
これにより、同じ情報を繰り返し提示するのではなく、topic に日々の情報蓄積を残す。

## Collection Record Policy
`collect-and-present` では、daily watch 対象 topic ごとに次を行う。

1. 当日確認した情報を `topics/{{topic}}/inbox/YYYY-MM-DD-daily.md` に保存する
2. 同じ日に同じ topic の daily メモがある場合は、新規ファイルを増やさず既存ファイルを更新する
3. `sources.json` に daily メモへの source entry を追加する
4. 既に同じ `path` の source entry がある場合は重複追加せず、必要に応じて既存 entry を更新する
5. 重要な変化があった場合のみ `summary.md` / `tasks.json` / `decisions.md` を更新する

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
- 技術記事は、流行度より学習価値と持ち帰れる設計・実装観点を優先する
- AIニュースは、発表の羅列ではなく実務への影響を含める
- `product-idea-watch` は通常の daily 本文には出さず、分析閾値に達したときだけ通知する
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
4. ポケモンカード
5. 技術記事
6. ニーズ蓄積の通知
7. 出典
8. 次に見ること

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
