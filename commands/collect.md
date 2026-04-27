# Command: collect

## Purpose
外部情報やメモを topic の `inbox/` に取り込み、`sources.json` に登録する。

## Trigger
- 新しい URL を保存したい
- メモを知識ベースに追加したい
- 会話や調査結果を未整理情報として残したい

## Required Inputs
- `topic`
- `input_type`
  - `url`
  - `note`
  - `text`
  - `file`
- `payload`

## Optional Inputs
- `title`
- `tags`
- `collected_at`
- `source_label`

## Read Scope
- `agents/collector.md`
- `prompts/collector.prompt.md`
- `topics/{{topic}}/topic-manifest.json`
- `topics/{{topic}}/index.md`
- `topics/{{topic}}/sources.json`

## Write Scope
- `topics/{{topic}}/inbox/*`
- `topics/{{topic}}/sources.json`

## Execution Mode
- `dry-run`
- `proposal`
- `apply`

## Constraints
- 生データは `inbox/` にのみ保存する
- `summary.md` `decisions.md` `tasks.json` は変更しない
- 既存 source を削除しない
- `path` と `id` は重複させない
- topic が存在しない場合は作成せず失敗として返す
- `sources.json` は `schemas/sources.schema.json` に従う

## Output Contract
### dry-run
- 追加予定 topic
- 保存予定パス
- `sources.json` 追記予定の概要

### proposal
- `inbox_file_path`
- `inbox_markdown`
- `source_entry`
- `notes`

### apply
- `created_files`
- `updated_files`
- `source_entry`
- `notes`

## Failure Handling
以下のいずれかで失敗を返す。

- `topic_not_found`
- `invalid_input_type`
- `malformed_payload`
- `duplicate_source_candidate`

失敗時は以下を返す。

- `error_code`
- `message`
- `suggested_action`

## Success Criteria
- 入力情報が追跡可能な形で `inbox/` に保存される
- `sources.json` にスキーマ準拠の entry が追加される
- 後続の `organize` が処理可能な状態になる
