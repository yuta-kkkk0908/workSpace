# AGENT.md

## Role
あなたはこのリポジトリ内で動作する AI エージェントです。

このリポジトリは知識運用基盤であり、あなたは topic ごとの状態を安全に更新します。

`topics/` は主にローカル workspace、`sample-topics/` は公開サンプルとして扱います。

## Primary Objective
以下を安全かつ再現可能に実行すること。

- 情報の収集 (`collect`)
- 情報の整理 (`organize`)
- 情報の提示 (`present`)

## Mandatory Rules
### 1. 正本ファイルを守る
各 topic の正本は次の 5 つだけです。

- `topic-manifest.json`
- `summary.md`
- `decisions.md`
- `tasks.json`
- `sources.json`

同じ役割の別ファイルを作ってはいけません。

### 2. 生データは inbox に置く
- 未整理情報は必ず `inbox/` に保存する
- `inbox/` 以外に生データを置かない

### 3. ファイルを増殖させない
禁止例:

- `summary_v2.md`
- `new_summary.md`
- `final_summary.md`

更新が必要なら既存ファイルを更新します。

### 4. Command ベースで動く
直接の思いつきで作業せず、必ず command の契約に従います。

- `commands/collect.md`
- `commands/organize.md`
- `commands/present.md`

### 5. 書き込み範囲を守る
- `collect` は `inbox/` と `sources.json` のみ
- `organize` は正本ファイルのみ
- `present` は書き込み禁止

### 6. 推測を制限する
- 根拠のない判断は禁止
- 不明点は不明として明示する
- 未整理情報を確定情報として扱わない

## Execution Policy
### Default Mode
- `collect`: `apply` 可
- `organize`: まずは `proposal` 優先
- `present`: 読み取り専用

### Safe Operation
- 変更前に対象ファイルを読む
- topic の目的を `index.md` で確認する
- 更新範囲を超えない
- 差分を明確にする
- JSON はスキーマに従わせる
- 実運用データを公開サンプルへ混ぜない

## Reading Priority
1. `index.md`
2. `topic-manifest.json`
3. `summary.md`
4. `decisions.md`
5. `tasks.json`
6. `sources.json`
7. `inbox/`

## Output Policy
- 要点を先に出す
- 構造化して出す
- 冗長にしない
- 根拠が必要なら参照先を示す

## Failure Policy
以下の場合は処理を停止し、理由を返します。

- topic が存在しない
- 正本ファイルが欠けている
- JSON が不正
- 入力が曖昧すぎる

## Guiding Principle
この Repo では、AI に記憶させるのではなく、AI が読める形で知識を管理します。

## Final Constraint
便利さのために構造を壊してはいけません。
最優先は次の 3 つです。

- 一貫性
- 再現性
- 可読性
