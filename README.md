# AIOS (AI Operation System)

## Overview
AIOS は、気になる情報を AI が収集し、整理し、要約して、ユーザーに解説するための topic ベースの情報運用リポジトリです。

この Repo で扱うのはアプリの状態ではなく、ユーザーの関心領域ごとの情報蓄積です。
情報はローカルの `topics/<topic>/` に集約し、AI は集めた情報を正本ファイルへ整理してから説明します。

この Repo 自体は framework を GitHub で共有し、実運用データは workspace としてローカル保持する前提です。

## Startup Prompt
## Quick Start Words
新規チャットでも次の合言葉で起動できます。

- `今日の情報`: 標準 daily 実行（adaptive）
- `今日の情報 deep`: 深掘り daily 実行（deep）
- `取り逃し補完`: 不足日の daily を補完

## Terminal Shortcuts
収集系の機械処理は、次の短縮コマンドで回せます。

```bash
make inv-daily DATE=YYYY-MM-DD
make inv-deep DATE=YYYY-MM-DD
make inv-deep-cache DATE=YYYY-MM-DD
make daily-missing DATE=today DAYS=7
make topics-db-ingest DATE=YYYY-MM-DD
make needs-db-ingest DATE=YYYY-MM-DD
make needs-ai-queue LIMIT=20
```

- `inv-daily`: 軽量の投資パイプライン
- `inv-deep`: 深掘りの投資パイプライン
- `inv-deep-cache`: ネット取得を抑えた deep 実行
- `daily-missing`: 日次取り逃しの確認
- `topics-db-ingest`: 非投資トピックの日次メモを汎用DBへ投入
- `needs-db-ingest`: ニーズ収集ログを専用DBへ投入
- `needs-ai-queue`: 未整理ニーズをAI整理キューとして抽出

新規チャットでは、最初に次を貼ると安定します。

```text
AGENT.md と commands/daily.md を読んで、「今日の情報」をまとめて。
対象は topic-manifest.json の kind: daily-watch の topic。
出典URLを付け、未確認事項は未確認として明示して。
投資情報は売買助言ではなく、材料整理と確認観点に限定して。
```

用途別の起動プロンプトは [startup.prompt.md](/mnt/e/workSpace/prompts/startup.prompt.md) に置いています。

ニーズ収集を始める場合は、`prompts/startup.prompt.md` の `Need Watch` を使います。

## What This Repo Does
この Repo は、次の流れを安定して回すための仕組みです。

- 気になる情報を探す
- 必要なものだけ `inbox/` に残す
- 根拠を `sources.json` で追跡する
- `summary.md` や `decisions.md` に整理する
- ユーザーに短く分かりやすく解説する

topic ごとに次の 5 つを管理します。

- `topic-manifest.json`: topic の種類、公開可否、保存場所
- `summary.md`: 今どうなっているか
- `decisions.md`: 何をどう判断したか
- `tasks.json`: 次に何をするか
- `sources.json`: 何を根拠にしているか

そのうえで、AI の仕事を 3 つに分けます。

- `collect`: 未整理情報を集める
- `organize`: 未整理情報を正本に反映する
- `present`: 正本をもとに説明する
- `daily`: daily watch 対象から今日見るべき情報を説明する
- `need-watch`: 不満・要望・未充足ニーズを蓄積する

## Core Model
- `topic` = 関心領域ごとの情報蓄積
- `inbox/` = 未整理情報の置き場
- 正本ファイル = topic の現在状態
- `archive/` = 参照頻度が下がった情報の退避先

重要なのは、「AI に覚えさせる」のではなく「AI が毎回読める構造にする」ことです。

## Ops Docs
運用構想メモ（タスクスケジューラー / DB設計）:

- `doc/scheduler-data-pipeline-plan.md`
- `doc/topic-db-design.md`
- `doc/scheduler-job-catalog.md`
- `doc/script-role-catalog.md`
- `doc/OPERATION.md`
- `doc/OPERATION_CURRENT.md`

## Harness Model
この Repo には、情報収集・要約・解説を安定して回すためのハーネスも含めます。

- `AGENT.md`: AI が守る基本ルール
- `commands/`: 収集、整理、提示の契約
- `prompts/startup.prompt.md`: 新規チャット用の起動プロンプト
- `schemas/`: JSON の形
- `scripts/validate_topics.py`: topic の構造と根拠の検証
- `scripts/diff_topic.py`: topic 同士の差分確認
- `topic-manifest.json`: topic の扱い方を示すラベル

主目的は情報を分かりやすく届けることです。
ハーネスは、その作業を壊れにくく、再現しやすくするための支えです。

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
        ├── topic-manifest.json
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

## Topic Examples
実運用では、topic は関心領域ごとの蓄積になります。

- `investment-research`: 日本株高配当、JT を基準にした次の投資先候補
- `pokemon-card-watch`: ポケカ抽選落選後の追加抽選、受注、再販
- `tech-stack-reads`: 面白い技術記事、ニッチな実装、学びになる設計
- `ai-news-watch`: AI活用ニュース、実務に効く変化
- `product-idea-watch`: 開発アイディアにつながる不満、要望、未充足ニーズ

これらは GitHub に載せるものではなく、ローカル workspace の `topics/` に置きます。

## Canonical Files
各 topic の正本は次の 5 つです。

- `topic-manifest.json`
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

### `daily`
使いどころ:
「今日の情報」「今日のまとめ」と依頼されたとき

対象:
- `topic-manifest.json` の `kind: daily-watch`

通常の出力:
- AI活用・ニュース
- 投資
- ポケモンカード
- 技術記事

更新できる場所:
- 通常はなし
- 保存する場合だけ `collect-and-present` として topic を更新する

低消費で実行したいとき:

```text
AGENT.md と commands/daily.md を読んで、「今日の情報」を budget: lean でまとめて。
weekly / 5h レート節約のため、読むファイルと出力を最小化して。
product-idea-watch の裏収集は skip。
大規模バックテスト、unknown一括補完、週次/月次レポート生成はしない。
```

`budget: lean` では、差分確認、重要変化、期限到来 outcome、最新 rule brief の反映を優先します。
深掘りや大量補完は、レートに余裕があるときの `budget: deep` または明示依頼時に回します。

### `need-watch`
使いどころ:
開発アイディアの種になる不満、要望、未充足ニーズを蓄積したいとき

対象:
- `topics/product-idea-watch`

通常の動き:
- 10か所程度の情報源をローテーション巡回する
- daily には毎回出さない
- 分析できる程度に蓄積したら daily で通知する

更新できる場所:
- `topics/product-idea-watch/inbox/*`
- `topics/product-idea-watch/sources.json`
- 必要に応じて正本ファイル

### `rate-budget`
使いどころ:
weekly / 5h レート消費を抑えたいとき

通常の動き:
- 作業を `lean` / `balanced` / `deep` に仕分ける
- 今日やる最小作業と、レート回復後に回す深掘り作業を分ける
- daily や投資整理の読み込み範囲、出力量、裏収集の有無を決める

## Execution Modes
- `dry-run`: 何を読むか、何を変えるかだけを示す
- `proposal`: 更新案だけを返す
- `apply`: 実ファイルを更新する

## Rate Budgets
- `adaptive`: 推奨。軽量トリアージから始め、必要な投資情報だけ深掘りへ昇格する
- `lean`: 低消費。読むファイル、調査件数、出力を絞り、日次継続を優先する
- `balanced`: 通常。daily watch topic を一通り確認し、軽い蓄積も行う
- `deep`: 深掘り。バックフィル、unknown補完、ルール再集計、週次/月次レポート向け

通常の daily は `budget: adaptive` が向いています。
weekly rate が 50% 未満、または次回リセットまで時間がある場合は `budget: lean` を優先します。
投資情報では、`adaptive` により core check、gate decision、limited deep を分けます。
`tag-index` がある場合は、同種シグナルの過去タグを見て、深掘りすべきものだけを `deep_queue` に回します。

投資タグ索引を更新する場合:

```bash
make investment-tag-index
```

投資系 Python の実行レーン:

```bash
make investment-adaptive
make investment-rule-check DATE=2026-05-11
make investment-backtest-expand DATE=2026-05-11
```

バックテスト母集団は `configs/investment-seeds.json` で管理します。
別の母集団を試す場合は `SEED_LIST` を指定します。

```bash
make investment-backtest-expand DATE=2026-05-11 SEED_LIST=rough_backtest_full
make investment-backtest-expand DATE=2026-05-11 SEED_LIST=rough_backtest_short_focus
```

ネット取得を避け、既存キャッシュ/既存ファイルだけで回す場合:

```bash
make investment-backtest-expand DATE=2026-05-11 SEED_LIST=rough_backtest_light CACHE_ONLY=1
```

生成物を棚卸しする場合:

```bash
make investment-generated-inventory DATE=2026-05-11
```

cache-only や軽量運用の品質を見る場合:

```bash
make investment-quality DATE=2026-05-11
make investment-seed-compare DATE=2026-05-11 LEFT_SEED=rough_backtest_light RIGHT_SEED=rough_backtest_full
```

各スクリプトの役割と入出力は [INVESTMENT.md](/mnt/e/workSpace/scripts/INVESTMENT.md) にまとめています。

初期運用ルール:
- `collect`: `apply` 可
- `organize`: まずは `proposal` 中心
- `present`: 読み取り専用
- `daily`: まずは `present-only`

## HOWTO
### 新しい topic を作る
1. `templates/topic/` をもとにローカルの `topics/<topic>/` を作る
2. `topic-manifest.json` に topic の種類、公開可否、保存場所を書く
3. `index.md` にその topic の目的を書く
4. `summary.md` `decisions.md` `tasks.json` `sources.json` を初期化する
5. `inbox/` と `archive/` を作る

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

- `topics/*/topic-manifest.json`
- `topics/*/tasks.json`
- `topics/*/sources.json`
- `sample-topics/*/topic-manifest.json`
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
- `scripts/diff_topic.py`: topic 同士の差分を見る
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
python3 scripts/diff_topic.py topics/effective-ai-usage sample-topics/effective-ai-usage-demo
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
make diff-topic LEFT=topics/effective-ai-usage RIGHT=sample-topics/effective-ai-usage-demo
```

`make validate` は topic 構造に加えて、`configs/investment-seeds.json` の参照切れも確認します。

daily の実行漏れを確認する場合:

```bash
python3 scripts/check_daily_missing.py
python3 scripts/check_daily_missing.py --date yesterday
python3 scripts/check_daily_missing.py --date today --days 7
```

不足がある場合は `prompts/pending-daily/latest.prompt.md` に補完用プロンプトが生成されます。
通知用の短い本文は `prompts/pending-daily/latest.status.txt` に生成されます。
クリップボード用本文は `prompts/pending-daily/latest.clipboard.txt` に生成されます。
履歴は `prompts/pending-daily/archive/` に残ります。
タスクスケジューラーや cron では、このスクリプトを毎日実行して通知代わりに使います。

Windows 通知まで出す場合:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\check_daily_missing_toast.ps1 -RepoPath E:\workSpace -Date today -Days 7
```

漏れがある場合に補完プロンプトを自動でクリップボードへコピーする場合:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\check_daily_missing_toast.ps1 -RepoPath E:\workSpace -Date today -Days 7 -CopyPrompt
```

Toast 通知とクリップボードコピーを使う場合は、Windows タスクスケジューラーの「全般」で「ユーザーがログオンしているときのみ実行する」を選びます。
非対話セッションでは通知やクリップボードが効かないことがあります。
通知/コピー処理のログは `reminders-toast.log` に出ます。

`pre-commit` を使う場合:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

## Design Principles
- topic を作業単位として扱う
- 正本を固定する
- 生データは `inbox/` のみに置く
- ファイルを増殖させない
- AI が毎回読み直せる形を保つ
- 推測より根拠を優先する
- 手作業でも追える構造を維持する
