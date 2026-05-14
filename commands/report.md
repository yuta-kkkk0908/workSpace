# Command: report

## Purpose
蓄積された topic 情報を、週次または月次で整理し、読む価値のある変化だけを短く提示する。

全topicを毎回まとめて読むのではなく、未整理量、期限到来、強い変化がある topic だけを通知型で扱う。

## Trigger
- 週間レポート
- 週次レポート
- monthly report
- 月間レポート
- topic report
- レポート作成

## Required Inputs
- `period`
  - `weekly`
  - `monthly`
- `date`
  - 指定がなければ現在日付を使う

## Optional Inputs
- `topics`
  - 指定がなければ全 topic を対象にし、読む価値のある topic だけ出す
- `mode`
  - `proposal`
  - `apply`
- `detail`
  - `brief`
  - `normal`
  - `deep`

## Read Scope
- `AGENT.md`
- `commands/report.md`
- `topics/*/topic-manifest.json`
- `topics/{{topic}}/index.md`
- `topics/{{topic}}/summary.md`
- `topics/{{topic}}/decisions.md`
- `topics/{{topic}}/tasks.json`
- `topics/{{topic}}/sources.json`
- 必要に応じて `topics/{{topic}}/inbox/*`

## Write Scope
- `topics/{{topic}}/inbox/*report*.md`
- `topics/{{topic}}/sources.json`
- 必要に応じて `topics/{{topic}}/summary.md`
- 必要に応じて `topics/{{topic}}/tasks.json`

## Execution Mode
- `proposal`
- `apply`

## Report Selection Policy
全topicを必ず本文に出す必要はない。
次のいずれかに当てはまる topic を優先する。

- 未整理 source が一定数以上ある
- market signals の T+1 / T+5 / T+20 が期限到来している
- need-watch の強いパターンが増えた
- daily で繰り返し出る重要テーマがある
- ユーザーの次アクションに関係する
- 前回レポートから明確な変化がある

変化がない topic は `N/C` として短く扱うか、省略する。

## Weekly Report
週次では、短く行動につながる粒度を優先する。

- 今週の重要変化
- 未整理 source
- market signal の結果更新
- need pattern の増加
- 来週見るべきもの

## Monthly Report
月次では、傾向と学習を優先する。

- 月間の主要テーマ
- シグナル別の当たり外れ
- ニーズの強い束
- 記事種/プロダクト種
- 方針変更候補
- 次月の重点

## Output Contract
### proposal
- `period`
- `target_topics`
- `report_candidates`
- `skip_topics`
- `notes`

### apply
- `created_files`
- `updated_files`
- `source_entries`
- `report_summary`
- `next_actions`

## Success Criteria
- 全topicを一気に読まなくても、重要な変化だけ把握できる
- topic単位で深掘りするか判断できる
- 日々の蓄積が週次/月次の学習に変換される
