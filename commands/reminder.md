# Command: reminder

## Purpose
daily の実行漏れを検知し、Codex に貼る補完用プロンプトを生成する。

この command は情報収集そのものを自動実行しない。
タスクスケジューラーや cron からローカルスクリプトを起動し、漏れがあればユーザーに通知するための運用補助として使う。

## Trigger
- daily reminder
- リマインダー
- 今日の情報の実行漏れ確認
- daily漏れ確認
- 取り忘れ確認

## Required Inputs
- `date`
  - 指定がなければ現在日付を使う

## Optional Inputs
- `mode`
  - `check`
  - `generate-prompt`
- `prompt_path`
  - 指定がなければ `prompts/pending-daily.prompt.md`

## Read Scope
- `topics/*/topic-manifest.json`
- `topics/*/inbox/*`
- `commands/daily.md`

## Write Scope
- `prompts/pending-daily.prompt.md`

## Local Script
実行漏れ確認には次を使う。

```bash
python3 scripts/check_daily_missing.py
```

昨日分を確認する場合:

```bash
python3 scripts/check_daily_missing.py --date yesterday
```

特定日を確認する場合:

```bash
python3 scripts/check_daily_missing.py --date 2026-05-03
```

直近7日分を確認する場合:

```bash
python3 scripts/check_daily_missing.py --days 7
```

Windows 通知を出す場合:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\check_daily_missing_toast.ps1 -RepoPath E:\workSpace -Date today -Days 7
```

漏れがある場合に、補完プロンプトをクリップボードへコピーする場合:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\check_daily_missing_toast.ps1 -RepoPath E:\workSpace -Date today -Days 7 -CopyPrompt
```

毎日21時に、当日を含む直近7日分の漏れを確認する場合:

```bash
python3 scripts/check_daily_missing.py --date today --days 7
```

## Expected Files
対象日は次のファイルがあるか確認する。

- `topics/<daily-watch-topic>/inbox/YYYY-MM-DD-daily.md`
- `topics/investment-research/inbox/YYYY-MM-DD-market-signals.md`
- `topics/product-idea-watch/inbox/YYYY-MM-DD-daily-background-need-watch.md`

## Output
不足がある場合:

- 標準出力に missing file を出す
- `prompts/pending-daily/latest.prompt.md` に補完用プロンプトを書く
- `prompts/pending-daily/latest.status.txt` に、Codexへそのまま貼れる短い実行文を含む通知本文を書く
- `prompts/pending-daily/latest.clipboard.txt` に、クリップボード用のプロンプト本文を書く
- `prompts/pending-daily/archive/` に日付付き履歴を残す
- 複数日チェックの場合は、不足日の一覧と最初に補完すべき日を書く
- exit code `1` を返す

不足がない場合:

- 揃っていることを出す
- `prompts/pending-daily/latest.prompt.md` に present-only 用の短いプロンプトを書く
- `prompts/pending-daily/latest.status.txt` に OK の短い本文を書く
- exit code `0` を返す

## Scheduler Examples
### Windows Task Scheduler
WSL 上の repo を使う場合の例:

```text
Program: wsl.exe
Arguments: bash -lc 'cd /mnt/e/workSpace && python3 scripts/check_daily_missing.py'
```

毎日21:00に当日を含む直近7日分を確認する例:

```text
Program: wsl.exe
Arguments: bash -lc 'cd /mnt/e/workSpace && python3 scripts/check_daily_missing.py --date today --days 7'
```

Windows Python と通知を使う例:

```text
Program: powershell.exe
Arguments: -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\check_daily_missing_toast.ps1 -RepoPath E:\workSpace -Date today -Days 7 -CopyPrompt
Start in: E:\workSpace
```

漏れがない日も通知したい場合は、末尾に `-NotifyOk` を付ける。

### Windows Task Scheduler Notes
- Toast 通知とクリップボードコピーを使う場合は、タスクの「全般」で「ユーザーがログオンしているときのみ実行する」を選ぶ
- 「ユーザーがログオンしているかどうかにかかわらず実行する」だと、非対話セッションになり、通知やクリップボードが効かないことがある
- デバッグ時は PowerShell 引数に `-NoExit` を付けるか、`reminders-toast.log` を確認する
- 通常ログは `reminders.log`、通知/コピー処理のログは `reminders-toast.log` に出る

昨日分を毎朝確認する場合:

```text
Program: wsl.exe
Arguments: bash -lc 'cd /mnt/e/workSpace && python3 scripts/check_daily_missing.py --date yesterday'
```

### cron
毎日 23:00 に当日分を確認する例:

```cron
0 23 * * * cd /mnt/e/workSpace && python3 scripts/check_daily_missing.py
```

毎朝 08:00 に昨日分を確認する例:

```cron
0 8 * * * cd /mnt/e/workSpace && python3 scripts/check_daily_missing.py --date yesterday
```

毎日 21:00 に直近7日分を確認する例:

```cron
0 21 * * * cd /mnt/e/workSpace && python3 scripts/check_daily_missing.py --date today --days 7
```

## Success Criteria
- daily の実行漏れが目視できる
- Codex に貼る補完プロンプトが生成される
- 自動収集できない環境でも、取り忘れを翌日補完できる
