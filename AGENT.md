# AGENT.md

## Role
あなたはこのリポジトリ内で動作する AI エージェントです。

このリポジトリは、ユーザーの気になる情報を収集し、整理し、要約して解説するための情報運用基盤です。
あなたは topic ごとの情報蓄積を安全に更新します。

`topics/` は主にローカル workspace、`sample-topics/` は公開サンプルとして扱います。

## Primary Objective
以下を安全かつ再現可能に実行すること。

- 情報の収集 (`collect`)
- 情報の整理 (`organize`)
- 情報の提示 (`present`)
- 今日の情報の提示 (`daily`)
- 不満・ニーズの蓄積 (`need-watch`)

目的は、ユーザーが知りたい情報を短時間で理解できる状態にすることです。
ハーネスはそのための補助であり、目的そのものではありません。

## Mandatory Rules
### 1. 正本ファイルを守る
各 topic の正本は次の 5 つだけです。

- `topic-manifest.json`
- `summary.md`
- `decisions.md`
- `tasks.json`
- `sources.json`

同じ役割の別ファイルを作ってはいけません。

例外:
- command が明示的に読む補助ルールブックは作成してよい
- 例: `topics/investment-research/signal-rules.md`
- 補助ルールブックは正本そのものではなく、daily / market-signal / organize の判断基準を揃えるための運用文書として扱う
- 補助ルールブックを増やす場合は、対応する command の Read Scope と更新方針に明記する

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
- `commands/daily.md`
- `commands/need-watch.md`
- `commands/market-signal.md`
- `commands/investment-organize.md`
- `commands/need-organize.md`
- `commands/report.md`
- `commands/reminder.md`
- `commands/rate-budget.md`

### 5. 書き込み範囲を守る
- `collect` は `inbox/` と `sources.json` のみ
- `organize` は正本ファイルのみ
- `present` は書き込み禁止
- `daily` は通常 `collect-and-present` とし、ユーザーが明示した場合だけ `present-only` にする
- `need-watch` は `product-idea-watch` の `inbox/` と `sources.json` を中心に更新する

### 6. 推測を制限する
- 根拠のない判断は禁止
- 不明点は不明として明示する
- 未整理情報を確定情報として扱わない

### 7. レート残量を守る
- weekly / 5h レート残量が厳しい場合は、`budget: lean` を優先する
- `budget: lean` では、読むファイル、調査件数、出力量を絞る
- `inbox/` と `sources.json` の全量読みは避け、日付指定ファイル、最新ファイル、正本ファイルを優先する
- 大量バックフィル、unknown一括補完、週次/月次レポート、投資バックテスト拡張は `budget: deep` または明示依頼時のみ行う
- 継続性を優先し、深掘りが必要なものは `next_watch` に回す

## Execution Policy
### Default Mode
- `collect`: `apply` 可
- `organize`: まずは `proposal` 優先
- `present`: 読み取り専用
- `daily`: `apply` / `collect-and-present` を既定にし、当日分を `inbox/` と `sources.json` に蓄積する

### Rate Budget
- `lean`: 低消費。差分、重要変化、期限到来 outcome、最新 dashboard を優先する
- `balanced`: 通常。daily watch topic を一通り確認する
- `deep`: 深掘り。バックフィル、unknown補完、ルール再集計、週次/月次レポートを許可する

## Trigger Policy
ユーザーが「今日の情報」「今日のまとめ」「daily」と依頼した場合は、`commands/daily.md` に従います。
新規チャットでも、会話履歴ではなく Repo 内の daily command を基準にします。
合言葉は `今日の情報` (標準), `今日の情報 deep` (深掘り), `取り逃し補完` (不足日補完) として扱います。
ユーザーが「ニーズ収集」「不満収集」「開発アイディア収集」と依頼した場合は、`commands/need-watch.md` に従います。
ユーザーが「投資情報の整理」「投資整理」「シグナルチェック」と依頼した場合は、`commands/investment-organize.md` に従います。
ユーザーが「ニーズの整理」「ニーズ整理」「記事ネタ整理」と依頼した場合は、`commands/need-organize.md` に従います。
ユーザーが「ニーズを分析」と依頼した場合は、未分析キューを対象に `needs-triage` を実行します。`prompts/needs-triage.prompt.md` の内容を内部的に適用し、貼り付け作業をユーザーに要求しません。
ユーザーが「週間レポート」「週次レポート」「月間レポート」と依頼した場合は、`commands/report.md` に従います。
ユーザーが「リマインダー」「daily漏れ確認」「取り忘れ確認」と依頼した場合は、`commands/reminder.md` に従います。

## Daily Operation Contract
`今日の情報` の運用は次を必須とする。

1. まず DB を確認する（`data/` 配下の topic DB、特に投資は `data/investment.db`）。
2. DB に当日データがある場合は、DB を正として要約する。
3. DB に不足がある topic だけ、`topics/*/inbox` を補完参照する。
4. 「ファイルだけ読んで要約」は禁止。DB確認を省略してはならない。
5. 回答では、DB確認の有無と、不足補完で読んだファイルの有無を明示する。

## Global DB-First Contract
全topic（汎用 topic / 投資 topic）で次を原則とする。

1. 判定・要約・提示の一次参照はDBを正とする（topic DB / needs DB / investment DB / ops DB）。
2. `topics/*/inbox` の生成ファイルは監査ログ・再現ログとして扱う。
3. DBに同等データがある処理は、ファイル依存を避けてDB優先で読む。
4. `inbox` 生成物は保持期間ベースで定期クリーンアップしてよい。

補足:
- `needs` 系（`product-idea-watch`）も同様に DB-first とし、`needs.db` の内容を優先参照する。
- アラート/運用ログ系も同様に DB-first とし、`ops.db`（scheduler/discord logs）を優先参照する。

## Investment DB-First Contract
投資系（`investment-research`）は次を必須とする。

1. 正式な判定・シナリオ生成・集計は `data/investment.db` を正とする。
2. `topics/investment-research/inbox` の生成物（`entry-candidates`/`opening-scenarios`/`rule-*`/`rough-backtest-*` など）は監査ログとして扱う。
3. 投資系スクリプトは、同等データがDBにある場合はDBを優先し、ファイル依存を避ける。
4. 生成ファイルの長期保持は前提にせず、運用で定期クリーンアップしてよい。

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
この Repo では、AI に記憶させるのではなく、AI が読める形でユーザーの関心情報を管理します。

## Final Constraint
便利さのために構造を壊してはいけません。
最優先は次の 3 つです。

- 一貫性
- 再現性
- 可読性
