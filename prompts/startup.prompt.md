# Startup Prompt

新規チャットでこの Repo を使うときは、最初に次のどれかを貼る。

## Daily
```text
AGENT.md と commands/daily.md を読んで、「今日の情報」を budget: adaptive でまとめて。
対象は topic-manifest.json の kind: daily-watch の topic。
投資情報は軽量トリアージから始め、active rule、期限到来 outcome、重要開示、外部トリガー、相対強弱の例外があるものだけ深掘り候補にして。
tag-index がある場合は、同種シグナルの既存タグを参照して deep_queue / no_change を切り分けて。
出典URLを付け、未確認事項は未確認として明示して。
投資情報は売買助言ではなく、材料整理と確認観点に限定して。
```

## Adaptive Investment Daily
```text
AGENT.md と commands/daily.md と commands/rate-budget.md を読んで、「今日の情報」を budget: adaptive でまとめて。
投資情報は core check → gate decision → 必要なものだけ limited deep の順で処理して。
tag-index がある場合は、同種シグナルの既存タグを参照して deep_queue / no_change を切り分けて。
product-idea-watch の裏収集は skip。
バックテスト拡張、unknown一括補完、週次/月次レポート生成はしない。
deep_queue に回したものは次に見ることへ残して。
売買助言ではなく、材料整理と確認観点に限定して。
```

## Low Rate Daily
```text
AGENT.md と commands/daily.md を読んで、「今日の情報」を budget: lean でまとめて。
weekly / 5h レート節約のため、読むファイルと出力を最小化して。
対象は topic-manifest.json の kind: daily-watch の topic。
product-idea-watch の裏収集は skip。
投資情報は、外部トリガー、市場地合い、重要開示、期限到来 outcome、最新 daily-rule-brief の反映を優先して。
大規模バックテスト、unknown一括補完、週次/月次レポート生成はしない。
出典URLを付け、未確認事項は未確認として明示して。
```

## Low Rate Investment Check
```text
AGENT.md と commands/investment-organize.md を読んで、投資情報を budget: lean で整理して。
期限到来した T+1/T+5/T+20、当日重要シグナル、最新 rule dashboard / rule history の確認だけ行って。
バックテスト拡張、unknown一括補完、過去分の大量再評価はしない。
売買助言ではなく、材料整理と確認観点に限定して。
```

## Rate Budget Review
```text
AGENT.md と commands/rate-budget.md を読んで、現在の作業を lean / balanced / deep に仕分けて。
weekly / 5h レート消費を抑えるため、今日やるべき最小作業と後回しにする deep 作業を分けて提案して。
```

## Pending Daily
```text
prompts/pending-daily/latest.prompt.md を読んで、そこに書かれた targetDate の daily を補完して。
AGENT.md と commands/daily.md のルールに従い、既存ファイルがある場合は増殖させず更新して。
```

## Reminder
```text
AGENT.md と commands/reminder.md を読んで、daily の実行漏れ確認の運用を説明して。
必要なら scripts/check_daily_missing.py の使い方と、prompts/pending-daily.prompt.md の貼り方を示して。
```

## Need Watch
```text
AGENT.md と commands/need-watch.md を読んで、product-idea-watch に不満・要望・未充足ニーズを収集して。
10か所程度の情報源をローテーションで巡回し、個人情報は保存しないで。
daily には通常出さず、分析できる量が溜まったときだけ通知する前提で蓄積して。
```

## General
```text
AGENT.md を読んで、この Repo の運用ルールに従って作業して。
作業内容に対応する commands/ の定義を確認してから進めて。
```

## Collect
```text
AGENT.md と commands/collect.md を読んで、この情報を該当 topic の inbox と sources.json に追加して。
正本ファイルはまだ更新しないで。
```

## Organize
```text
AGENT.md と commands/organize.md を読んで、指定 topic の inbox 情報を正本ファイルへ整理する proposal を出して。
必要なら summary.md / decisions.md / tasks.json / sources.json の更新案を分けて示して。
```

## Present
```text
AGENT.md と commands/present.md を読んで、指定 topic の現状を正本ファイルに基づいて短く説明して。
根拠ファイルも示して。
```
