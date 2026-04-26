# AIOS (AI Operation System)

## Overview
AIOS は、AI が読みやすい形で情報を蓄積し、整理し、提示するためのファイルベース運用リポジトリです。

この Repo で扱うのはアプリの状態ではなく、意思決定に必要な知識の状態です。
情報はローカルの `topics/<topic>/` に集約し、AI は決められた正本ファイルだけを読んで更新します。

この Repo 自体は framework を GitHub で共有し、実運用データは workspace としてローカル保持する前提です。

## What This Repo Does
この Repo では、topic ごとに次の 4 つを管理します。

- `summary.md`: 今どうなっているか
- `decisions.md`: 何をどう判断したか
- `tasks.json`: 次に何をするか
- `sources.json`: 何を根拠にしているか

そのうえで、AI の仕事を 3 つに分けます。

- `collect`: 未整理情報を集める
- `organize`: 未整理情報を正本に反映する
- `present`: 正本をもとに説明する

## Core Model
- `topic` = 管理単位
- `inbox/` = 未整理情報の置き場
- 正本ファイル = topic の現在状態
- `archive/` = 参照頻度が下がった情報の退避先

重要なのは、「AI に覚えさせる」のではなく「AI が毎回読める構造にする」ことです。

## Directory Layout
```text
.
├── AGENT.md
├── README.md
├── agents/
├── commands/
├── examples/
├── prompts/
├── sample-topics/
├── schemas/
├── scripts/
├── templates/
│   └── present/
└── topics/
    └── <topic>/
        ├── index.md
        ├── summary.md
        ├── decisions.md
        ├── tasks.json
        ├── sources.json
        ├── inbox/
        └── archive/
```

`topics/` はローカル workspace です。通常は `.gitignore` で除外し、GitHub には載せません。
公開用のサンプルは `sample-topics/` に置きます。

## Framework vs Workspace
この Repo は 2 層に分けて考えるのが自然です。

- framework:
  - `AGENT.md`
  - `commands/`
  - `prompts/`
  - `schemas/`
  - `scripts/`
  - `templates/`
  - `examples/`
  - `sample-topics/`
- workspace:
  - `topics/`
  - 日々の収集結果
  - `inbox/` の生データ
  - 個別調査メモ
  - 監視対象や個人判断に紐づく情報

これにより、GitHub では仕組みを共有しつつ、運用データはローカルや private な保管先で扱えます。

## Canonical Files
各 topic の正本は次の 4 つです。

- `summary.md`
- `decisions.md`
- `tasks.json`
- `sources.json`

これ以外に同種のファイルを増やしません。
例えば `summary_v2.md` や `final_summary.md` は作りません。

## How We Handle Information
### 1. 新しい情報を受け取る
URL、会話メモ、調査結果、ローカルファイル由来の内容などを受け取ります。

### 2. まだ結論にしない
受け取った内容はまず `inbox/` に保存します。
未整理情報は、まだ正本ではありません。

### 3. 根拠を追跡可能にする
同時に `sources.json` に source entry を追加し、どの情報がどこから来たかを残します。

### 4. 整理して状態を更新する
`organize` が `inbox/` と既存の正本を読み、必要な内容だけを `summary.md` `decisions.md` `tasks.json` `sources.json` に反映します。

### 5. 正本をもとに説明する
人に見せるときは `present` が正本を優先して読みます。
未整理情報は補助根拠としてのみ使います。

## Command Model
### `collect`
使いどころ:
新しい情報を topic に取り込みたいとき

扱う内容:
- URL
- note
- text
- file

更新できる場所:
- `topics/<topic>/inbox/*`
- `topics/<topic>/sources.json`

### `organize`
使いどころ:
`inbox/` の情報を正本に反映したいとき

更新できる場所:
- `topics/<topic>/summary.md`
- `topics/<topic>/decisions.md`
- `topics/<topic>/tasks.json`
- `topics/<topic>/sources.json`

### `present`
使いどころ:
現在の状況、判断、次アクション、根拠を説明したいとき

更新できる場所:
- なし

## Execution Modes
- `dry-run`: 何を読むか、何を変えるかだけを示す
- `proposal`: 更新案だけを返す
- `apply`: 実ファイルを更新する

初期運用ルール:
- `collect`: `apply` 可
- `organize`: まずは `proposal` 中心
- `present`: 読み取り専用

## HOWTO
### 新しい topic を作る
1. `templates/topic/` をもとにローカルの `topics/<topic>/` を作る
2. `index.md` にその topic の目的を書く
3. `summary.md` `decisions.md` `tasks.json` `sources.json` を初期化する
4. `inbox/` と `archive/` を作る

手動で作る代わりに、次のスクリプトも使えます。

```bash
python3 scripts/new_topic.py product-research --purpose "プロダクト調査の論点と判断を管理する。"
```

タイトルと slug を分けたい場合:

```bash
python3 scripts/new_topic.py "Product Research" --slug product-research --title "Product Research" --purpose "プロダクト調査の論点と判断を管理する。"
```

調査用の初期タスクも入れたい場合:

```bash
python3 scripts/new_topic.py "Vendor Review" --slug vendor-review --from-example research --open-task-id-prefix review --purpose "ベンダー比較の判断を管理する。"
```

### 情報を追加する
1. topic を決める
2. 元情報を `inbox/` に markdown で置く
3. `sources.json` に entry を追加する
4. まだ結論は書かない

### 情報を整理する
1. `index.md` で topic の目的を確認する
2. `summary.md` へ現状を反映する
3. 判断があれば `decisions.md` に理由付きで残す
4. 次アクションを `tasks.json` に落とす
5. 処理した source は `sources.json` で `new` から `organized` に更新する

### 人に説明する
1. まず `summary.md` を見る
2. 判断理由は `decisions.md` を見る
3. 次アクションは `tasks.json` を見る
4. 根拠が必要なときだけ `sources.json` と `inbox/` を辿る

## Example Flow
### 1. collect で扱うもの
入力:

```text
topic: ai-tool
input_type: note
title: Cursor comparison memo
payload: Cursor と Codex の差分メモ
```

保存先のイメージ:

- `topics/ai-tool/inbox/2026-04-26-cursor-comparison-memo.md`
- `topics/ai-tool/sources.json` に source entry を追加

### 2. organize でやること
読み取り:

- `index.md`
- `summary.md`
- `decisions.md`
- `tasks.json`
- `sources.json`
- `inbox/*`

反映先のイメージ:

- `summary.md`: 比較の現状を更新
- `decisions.md`: 採用判断や保留理由を追記
- `tasks.json`: 次に試す項目を追加
- `sources.json`: status を `new` から `organized` に更新

### 3. present で返すもの
例:

- 現状: Codex を主軸に検証中
- 判断: Cursor は比較対象として保留
- 次アクション: 実運用シナリオで再比較
- 根拠: `sources.json` に登録されたメモと `summary.md`

より具体的な入出力例は `examples/` に置いています。

- `examples/collect-example.md`
- `examples/organize-example.md`
- `examples/present-example.md`

対応するサンプル topic も入っています。

- `sample-topics/ai-tool-demo/`
- `sample-topics/daily-watch-demo/`

## Validation
JSON の整合性はスキーマで検証できます。

- `schemas/tasks.schema.json`
- `schemas/sources.schema.json`
- `scripts/validate_topics.py`

実行例:

```bash
python3 scripts/validate_topics.py
```

このスクリプトは次を検査します。

- `topics/*/tasks.json`
- `topics/*/sources.json`
- `sample-topics/*/tasks.json`
- `sample-topics/*/sources.json`
- `templates/topic/tasks.json`
- `templates/topic/sources.json`
- topic に必要な正本ファイルの有無
- `inbox/` `archive/` ディレクトリの有無
- `tasks.json` の重複 `id`
- `sources.json` の重複 `id` と重複 `path`
- `sources.json` から参照するファイルパスの実在

CI でも同じ検証を回せるようにしています。

- `.github/workflows/validate.yml`
- `.pre-commit-config.yaml`

## Scripts
- `scripts/new_topic.py`: template から topic を作る
- `scripts/export_sample_topic.py`: local topic を `sample-topics/` に複製する
- `scripts/validate_topics.py`: JSON と topic 構造を検証する

## Public Samples
GitHub に載せる topic サンプルは `sample-topics/` に置きます。

- `sample-topics/ai-tool-demo/`
- `sample-topics/daily-watch-demo/`

実運用の収集データは `topics/` で持ち、公開対象とは分けます。

## Publish Checklist
`topics/` の内容を `sample-topics/` に出す前に、次を確認します。

1. 個人名、メール、アカウント情報、社内固有名詞が残っていない
2. API key、token、secret、password などの機微情報がない
3. 個別の投資助言や private な判断材料が残っていない
4. 元記事依存の要約が公開前提として過度に詳細すぎない
5. `sources.json` の参照先ファイルが sample 内に揃っている
6. `python3 scripts/validate_topics.py` が通る

ローカル topic を sample 化するには次を使います。

```bash
python3 scripts/export_sample_topic.py effective-ai-usage --sample-slug effective-ai-usage-demo
```

または:

```bash
make export-sample TOPIC=effective-ai-usage SAMPLE=effective-ai-usage-demo
```

## Present Templates
`present` の出力を揃えたいときは `templates/present/` を使えます。

- `templates/present/overview.md`
- `templates/present/status.md`
- `templates/present/decisions.md`
- `templates/present/tasks.md`
- `templates/present/evidence.md`

## Local Commands
ローカルでは次のコマンドで運用できます。

```bash
make validate
make new-topic TOPIC=product-research PURPOSE="プロダクト調査の論点と判断を管理する。"
make export-sample TOPIC=effective-ai-usage SAMPLE=effective-ai-usage-demo
```

`pre-commit` を使う場合:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## Design Principles
- 正本を固定する
- 生データは `inbox/` のみに置く
- ファイルを増殖させない
- AI が毎回読み直せる形を保つ
- 推測より根拠を優先する
- 手作業でも追える構造を維持する
