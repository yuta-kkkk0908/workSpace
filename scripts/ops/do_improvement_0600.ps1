$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

. (Join-Path $repo "scripts\ops\task_runner_common.ps1")
$python = Get-AiosPythonPath -Repo $repo

$d = Get-Date -Format yyyy-MM-dd
& $python "scripts/run_ops_scheduler.py" --slot improvement --date $d
exit $LASTEXITCODE
