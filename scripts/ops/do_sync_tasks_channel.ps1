$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

. (Join-Path $repo "scripts\ops\task_runner_common.ps1")
$python = Get-AiosPythonPath -Repo $repo

# Operation policy:
# - Periodic monitor stays on.
# - React only to Japanese task keywords.
# - Execute and reply only for matched task commands.
& $python -X utf8 "scripts/notify/sync_tasks_channel_bot.py" --limit 50 --enable-task-exec --enable-replies --only-task-keywords
exit $LASTEXITCODE
