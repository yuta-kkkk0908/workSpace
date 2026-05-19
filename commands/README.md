# Commands

- `collect`: 未整理情報を `inbox/` と `sources.json` に追加する
- `organize`: `inbox/` の情報を正本ファイルへ整理する
- `present`: 正本ファイルをもとに情報を提示する
- `daily`: daily watch 対象の topic から今日見るべき情報を提示する
- `need-watch`: ネット上の不満・要望・未充足ニーズを蓄積する
- `market-signal`: 投資シグナルの仮説と結果を蓄積する
- `investment-organize`: 投資情報の未整理分とシグナル結果を整理する
- `investment-tag-index`: 投資シグナルにタグを付け、軽量検索用インデックスを更新する
- `need-organize`: 未整理ニーズをパターン、記事種、プロダクト種へ整理する
- `needs-triage`: Python一次トリアージ結果をCodexで二次レビューして反映する
- `report`: topic 情報を週次/月次で通知型に整理する
- `reminder`: daily の実行漏れを検知し、補完用プロンプトを生成する
- `rate-budget`: weekly / 5h レート消費を抑えるため、作業を lean / balanced / deep に仕分ける

## Execution Modes
- `dry-run`
- `proposal`
- `apply`

## Initial Policy
- `collect`: `apply` allowed
- `organize`: `proposal` first
- `present`: read-only
- `daily`: `collect-and-present` default
- `need-watch`: `proposal` first, `apply` allowed for workspace data
- `market-signal`: `apply` allowed for workspace data
- `investment-organize`: `proposal` first, `apply` allowed after scope is clear
- `investment-tag-index`: local script execution; generated index update allowed
- `need-organize`: `proposal` first, `apply` allowed after scope is clear
- `needs-triage`: `apply` allowed for queue-based triage updates
- `report`: `proposal` first, `apply` allowed after target topics are clear
- `reminder`: local script execution only; generated prompt update allowed
- `rate-budget`: read first when rate is constrained; prefer `lean`

## Investment Python Lanes
- `make investment-adaptive`: daily後の軽量索引更新
- `make investment-rule-check DATE=YYYY-MM-DD`: 既存データのルール候補確認
- `make investment-backtest-expand DATE=YYYY-MM-DD`: deep用の重い拡張処理

詳細は `scripts/INVESTMENT.md` を参照。

- `investment-ops-checklist`: 投資運用の朝/夜チェックリスト
