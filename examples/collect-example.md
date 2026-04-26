# Collect Example

## Scenario
`ai-tool` topic に、Codex と Cursor の比較メモを追加する。

## Input
```yaml
topic: ai-tool
input_type: note
title: Cursor comparison memo
payload: |
  Cursor と Codex を比較したメモ。
  差分は補完の速さ、エージェント挙動、既存 Repo との相性。
tags:
  - cursor
  - codex
  - comparison
source_label: manual-note
collected_at: 2026-04-26T09:30:00+09:00
```

## Inbox Output
保存先イメージ:

`topics/ai-tool/inbox/2026-04-26-cursor-comparison-memo.md`

```md
# Cursor comparison memo

## Source
- type: note
- source: manual-note
- collectedAt: 2026-04-26T09:30:00+09:00

## Notes
- Cursor と Codex を比較したメモ
- 差分は補完の速さ、エージェント挙動、既存 Repo との相性
```

## Source Entry Output
`topics/ai-tool/sources.json` に追記するイメージ:

```json
{
  "id": "src_20260426_002",
  "title": "Cursor comparison memo",
  "type": "note",
  "source": "manual-note",
  "path": "inbox/2026-04-26-cursor-comparison-memo.md",
  "url": "",
  "collectedAt": "2026-04-26T09:30:00+09:00",
  "status": "new",
  "tags": ["cursor", "codex", "comparison"]
}
```

## Notes
- この段階では `summary.md` `decisions.md` `tasks.json` は更新しない
- まずは追跡可能な形で未整理情報として残す
