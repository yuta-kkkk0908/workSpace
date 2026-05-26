$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

. (Join-Path $repo "scripts\ops\task_runner_common.ps1")
$python = Get-AiosPythonPath -Repo $repo

& $python "scripts/run_ops_scheduler.py" --slot inv-evening --date (Get-Date -Format yyyy-MM-dd)
$rc = $LASTEXITCODE
if ($rc -eq 0) {
  $stepRc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\notify\resend_pending_discord.ps1" -Arguments @("-Limit", "5")
  if ($stepRc -ne 0) { $rc = $stepRc }
  $stepRc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\notify\post_signal_discord.ps1"
  if ($stepRc -ne 0) { $rc = $stepRc }
  $stepRc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\notify\post_paper_stats_discord.ps1"
  if ($stepRc -ne 0) { $rc = $stepRc }
  $stepRc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\notify\post_signal_quality_alert.ps1"
  if ($stepRc -ne 0) { $rc = $stepRc }
}
exit $rc
