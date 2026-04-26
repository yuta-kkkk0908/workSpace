# Organize Example

## Scenario
`ai-tool` topic の `inbox/` に追加された比較メモを整理し、正本に反映する。

## Read Inputs
- `topics/ai-tool/index.md`
- `topics/ai-tool/summary.md`
- `topics/ai-tool/decisions.md`
- `topics/ai-tool/tasks.json`
- `topics/ai-tool/sources.json`
- `topics/ai-tool/inbox/2026-04-26-cursor-comparison-memo.md`

## Expected Summary Update
```md
# Summary

## Current State
- AI 開発支援ツール topic は作成済み
- Codex を主軸に比較観点を整理中

## Key Points
- Codex 運用メモが source として登録済み
- Cursor は比較対象として追加検討中

## Open Questions
- 比較軸をどう定義するか
- どのツール群を優先して評価するか
```

## Expected Decisions Update
```md
# Decisions

## Decision Log
- [2026-04-26] Cursor は比較対象として保留で管理する
  - Reason: 差分メモはあるが、実運用シナリオでの検証がまだ不足しているため
  - Impact: 直ちに採用判断せず、追加検証タスクを残す
```

## Expected Tasks Update
```json
[
  {
    "id": "task_001",
    "title": "Codexを知識提示エージェントとして使う最小要件を整理する",
    "status": "todo",
    "priority": "high",
    "relatedFiles": ["summary.md", "decisions.md"],
    "notes": "ディレクトリ標準構造の定義を優先"
  },
  {
    "id": "task_002",
    "title": "Cursor を実運用シナリオで再比較する",
    "status": "todo",
    "priority": "medium",
    "relatedFiles": ["summary.md", "decisions.md", "sources.json"],
    "notes": "補完速度だけでなく既存 Repo との相性も確認する"
  }
]
```

## Expected Sources Update
変更イメージ:

- 対象 source の `status` を `new` から `organized` に更新する

## Notes
- organize は未整理情報を正本へ反映する段階
- 反映時は topic の purpose を外さないことが大事
