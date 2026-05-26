$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

. (Join-Path $repo "scripts\ops\task_runner_common.ps1")
$python = Get-AiosPythonPath -Repo $repo

& $python "scripts/run_ops_scheduler.py" --slot inv-scenario --date (Get-Date -Format yyyy-MM-dd)
$rc = $LASTEXITCODE
if ($rc -eq 0) {
  $stepRc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\notify\resend_pending_discord.ps1" -Arguments @("-Limit", "5")
  if ($stepRc -ne 0) { $rc = $stepRc }
  $stepRc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\notify\post_scenario_discord.ps1"
  if ($stepRc -ne 0) { $rc = $stepRc }
}
exit $rc
