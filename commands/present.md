# Command: present

## Purpose
topic の正本情報をもとに、現状・判断・次アクション・根拠を短く明確に提示する。

## Trigger
- 今どうなっているか知りたい
- 何が決まっているか見たい
- 次に何をすべきか知りたい
- 根拠を確認したい

## Required Inputs
- `topic`
- `request_type`
  - `status`
  - `decisions`
  - `tasks`
  - `evidence`
  - `overview`

## Optional Inputs
- `query`
- `limit`
- `include_references`
- `source_ids`

## Read Scope
- `agents/presenter.md`
- `prompts/presenter.prompt.md`
- `templates/present/{{request_type}}.md`
- `topics/{{topic}}/index.md`
- `topics/{{topic}}/summary.md`
- `topics/{{topic}}/decisions.md`
- `topics/{{topic}}/tasks.json`
- `topics/{{topic}}/sources.json`

必要時のみ:
- `topics/{{topic}}/inbox/*`
- `topics/{{topic}}/archive/*`

## Write Scope
- なし

## Execution Mode
- `dry-run`
- `proposal`

## Constraints
- まず正本ファイルを優先して読む
- 未整理情報を確定情報として扱わない
- `request_type` に応じて出力を絞る
- `query` が曖昧な場合は推測しすぎず不足を明示する
- 回答は要点先出しにする

## Output Contract
### dry-run
- `files_to_read`
- `response_plan`

### proposal
- `answer`
- `references`
- `unresolved_points`

## Failure Handling
以下のいずれかで失敗を返す。

- `topic_not_found`
- `invalid_request_type`
- `missing_canonical_file`
- `insufficient_context`

失敗時は以下を返す。

- `error_code`
- `message`
- `suggested_action`

## Success Criteria
- ユーザーが現状を短時間で把握できる
- 必要に応じて根拠ファイルへ辿れる
- 正本に基づく一貫した提示になる
