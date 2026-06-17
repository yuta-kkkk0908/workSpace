# 2026-06-16 Repo Docs and DB-First Sweep

## Goal

実装状況を棚卸ししつつ、DB-first の方針に合わない古いドキュメントや重複ファイルを減らす。

README のリポジトリマップを実装実態に合わせて整え、潜在バグや改修候補を次の作業へ渡す。

## This Sweep

- `prompts/*-discord-message.md` の重複生成物を削除した
- `prompts/` から生成済みの `.txt` / 一時 `.md` / 状態ファイルを外し、ソース prompt 定義だけ残した
- `README.md` の repo map に `doc/` と `prompts/` の位置づけを補強した
- `commands/investment-tag-index.md` を追加して、Makefile 由来のコマンド案内の抜けを埋めた
- `topics/*/inbox` の 2 週間超ファイルを `archive/` に移し、`today-*` の一時ファイルも整理した

## Observations

### 1. 生成メッセージの重複

- `tmp/prompts/exit-analyzer-discord-message.txt`
- `tmp/prompts/generic-topics-discord-message.txt`
- `tmp/prompts/market-signals-discord-message.txt`
- `tmp/prompts/opening-scenarios-discord-message.txt`
- `tmp/prompts/paper-stats-discord-message.txt`

これらは `.txt` と内容差がほぼなく、外側のコードフェンスだけが違っていた。
今後は `.txt` を正本として扱う。

### 2. まだ整理余地があるドキュメント

- `doc/OPERATION_CURRENT.md` と `doc/ops/OPERATION_CURRENT.md` は責務がかなり近い
- `doc/topic-db-design.md` と `doc/policy/db_design.md` は旧版・新版の関係を再確認したい
- `doc/archive/task/` 配下は履歴として残すにしても、現行導線からの見え方を整えたい

### 3. 実装と案内のズレ

- `commands/README.md` にあるコマンドは、実装済みでも文書が欠けることがある
- `investment-tag-index` は今回文書を追加したが、同様の抜けが他にもある可能性がある
- `scripts/notify/*` の出力形式は一時ファイル扱いとして残すが、README/手順書側では source prompt と runtime output の区別を明示したい

## Potential Bugs / Risks

1. 旧 `README` や周辺 docs が `.md` の複製出力を前提にしていると、運用手順が古いまま残る可能性がある
2. `doc/OPERATION_CURRENT.md` 系の重複が続くと、実行手順と方針が二重管理になって差分が出やすい
3. `tmp/prompts/` の生成物が増え続けると、generated file と state file の境界が曖昧になる
4. `investment-tag-index` など Makefile 直結の導線は、command 文書が欠けると新規参加者が追いにくい

## Follow-Up Tasks

- [ ] `doc/OPERATION_CURRENT.md` と `doc/ops/OPERATION_CURRENT.md` の canonical を決める
- [ ] `doc/topic-db-design.md` と `doc/policy/db_design.md` の役割分担を整理する
- [ ] `README.md` に source prompt と runtime output の正本ルールをもう少し明確に書く
- [ ] `commands/README.md` と `commands/*.md` の一覧を突き合わせる
- [ ] `doc/archive/task/` の索引または整理方針を決める
- [ ] `scripts/notify/*` の `.md` 参照が残っていないか全体検索する

## Notes

- この作業では投資 DB や topic DB の中身は変更していない
- 今回の整理はドキュメントと生成物の重複削減が中心
- 実装の本丸は引き続き DB-first を正とする
