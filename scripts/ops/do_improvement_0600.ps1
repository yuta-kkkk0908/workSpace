$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

. (Join-Path $repo "scripts\ops\task_runner_common.ps1")
$python = Get-AiosPythonPath -Repo $repo

# 06:00 の改善ジョブは proposal だけで止めず、既定で execution まで進める。
if ([string]::IsNullOrWhiteSpace($env:ENABLE_IMPROVEMENT_EXECUTION)) {
  $env:ENABLE_IMPROVEMENT_EXECUTION = "1"
}

$d = Get-Date -Format yyyy-MM-dd
& $python "scripts/run_ops_scheduler.py" --slot improvement --date $d
exit $LASTEXITCODE
