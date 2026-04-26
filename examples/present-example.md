# Present Example

## Scenario
`ai-tool` topic の現状を短く説明する。

## Request
```yaml
topic: ai-tool
request_type: overview
include_references: true
```

## Expected Answer
```md
現状: ai-tool topic では Codex を主軸に比較観点を整理中です。

判断:
- Cursor は比較対象として保留で管理しています。

次アクション:
- 実運用シナリオで Cursor を再比較します。

根拠:
- summary.md
- decisions.md
- sources.json
```

## Notes
- `present` は正本ファイルを優先して読む
- `inbox/` は補助根拠としてのみ扱う
