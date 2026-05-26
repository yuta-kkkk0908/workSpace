$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

. (Join-Path $repo "scripts\ops\task_runner_common.ps1")
$python = Get-AiosPythonPath -Repo $repo

& $python -X utf8 "scripts/notify/sync_scenario_replies_bot.py" --limit 100
exit $LASTEXITCODE
