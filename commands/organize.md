# Command: organize

## Purpose
topic の `inbox/` にある未整理情報を整理し、正本ファイルの更新案または更新を行う。

## Trigger
- `inbox/` に未整理情報が溜まった
- topic の現状を正本に反映したい
- 次アクションを整理したい

## Required Inputs
- `topic`

## Optional Inputs
- `source_ids`
- `focus`
  - `summary`
  - `decisions`
  - `tasks`
  - `sources`
  - `all`
- `max_items`
- `mode_notes`

## Read Scope
- `agents/organizer.md`
- `prompts/organizer.prompt.md`
- `topics/{{topic}}/index.md`
- `topics/{{topic}}/summary.md`
- `topics/{{topic}}/decisions.md`
- `topics/{{topic}}/tasks.json`
- `topics/{{topic}}/sources.json`
- `topics/{{topic}}/inbox/*`

## Write Scope
- `topics/{{topic}}/summary.md`
- `topics/{{topic}}/decisions.md`
- `topics/{{topic}}/tasks.json`
- `topics/{{topic}}/sources.json`

## Execution Mode
- `dry-run`
- `proposal`
- `apply`

## Constraints
- 正本ファイル以外に summary 系ファイルを新規作成しない
- topic の purpose に反する分類をしない
- 根拠のない推測を書かない
- `focus` 指定がある場合は対象外ファイルを更新しない
- `source_ids` 指定がある場合はその source のみを対象にする
- `tasks.json` は `schemas/tasks.schema.json` に従う
- `sources.json` は `schemas/sources.schema.json` に従う
- tasks は実行可能な粒度で記述する
- decisions は理由付きで残す
- `sources.json` の status 更新は `new` → `organized` まで
- `archive/` への移動はこの command では行わない

## Output Contract
### dry-run
- `candidate_sources`
- `files_to_update`
- `expected_changes`
- `notes`

### proposal
- `summary_md`
- `decisions_md`
- `tasks_json`
- `sources_json`
- `change_notes`

### apply
- `updated_files`
- `change_summary`
- `changed_source_ids`
- `notes`

## Failure Handling
以下のいずれかで失敗を返す。

- `topic_not_found`
- `missing_canonical_file`
- `malformed_sources_json`
- `malformed_tasks_json`
- `no_target_sources`

失敗時は以下を返す。

- `error_code`
- `message`
- `blocking_files`
- `suggested_action`

## Success Criteria
- `summary.md` を見れば現状が分かる
- `decisions.md` を見れば判断履歴が分かる
- `tasks.json` を見れば次アクションが分かる
- 対象 source が `organized` 扱いになる
