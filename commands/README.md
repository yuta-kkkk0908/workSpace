# Commands

- `collect`: 未整理情報を `inbox/` と `sources.json` に追加する
- `organize`: `inbox/` の情報を正本ファイルへ整理する
- `present`: 正本ファイルをもとに情報を提示する
- `daily`: daily watch 対象の topic から今日見るべき情報を提示する
- `need-watch`: ネット上の不満・要望・未充足ニーズを蓄積する

## Execution Modes
- `dry-run`
- `proposal`
- `apply`

## Initial Policy
- `collect`: `apply` allowed
- `organize`: `proposal` first
- `present`: read-only
- `daily`: `present-only` first
- `need-watch`: `proposal` first, `apply` allowed for workspace data
