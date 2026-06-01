$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

. (Join-Path $repo "scripts\ops\task_runner_common.ps1")
$python = Get-AiosPythonPath -Repo $repo
$eventDate = Get-Date -Format yyyy-MM-dd

function Invoke-AiosPostStep {
  param(
    [string]$FilePath,
    [string]$Stage,
    [string[]]$Arguments = @()
  )
  $stepRc = Invoke-HiddenPowerShellFile -FilePath $FilePath -Arguments $Arguments
  if ($stepRc -ne 0) {
    $cat = Get-AiosErrorCategory -ExitCode $stepRc -Stage $Stage
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "inv-scenario" -Stage $Stage -Status "error" -ReturnCode $stepRc -EventDate $eventDate -Category $cat
  } else {
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "inv-scenario" -Stage $Stage -Status "ok" -ReturnCode 0 -EventDate $eventDate -Category "ok"
  }
  return $stepRc
}

& $python "scripts/run_ops_scheduler.py" --slot inv-scenario --date $eventDate
$rc = $LASTEXITCODE
if ($rc -eq 0) {
  $stepRc = Invoke-AiosPostStep -FilePath "E:\workSpace\scripts\notify\resend_pending_discord.ps1" -Stage "resend_pending_discord.ps1" -Arguments @("-Limit", "5")
  if ($stepRc -ne 0) { $rc = $stepRc }
  $stepRc = Invoke-AiosPostStep -FilePath "E:\workSpace\scripts\notify\post_scenario_discord.ps1" -Stage "post_scenario_discord.ps1"
  if ($stepRc -ne 0) { $rc = $stepRc }
}
exit $rc
