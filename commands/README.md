# Commands

- `collect`: 未整理情報を `inbox/` と `sources.json` に追加する
- `organize`: `inbox/` の情報を正本ファイルへ整理する
- `present`: 正本ファイルをもとに情報を提示する

## Execution Modes
- `dry-run`
- `proposal`
- `apply`

## Initial Policy
- `collect`: `apply` allowed
- `organize`: `proposal` first
- `present`: read-only
