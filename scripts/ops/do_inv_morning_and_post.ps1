$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

. (Join-Path $repo "scripts\ops\task_runner_common.ps1")
$python = Get-AiosPythonPath -Repo $repo
$eventDate = Get-Date -Format yyyy-MM-dd
$isWeekend = @("Saturday","Sunday") -contains (Get-Date).DayOfWeek

function Invoke-AiosPostStep {
  param(
    [string]$FilePath,
    [string]$Stage,
    [string[]]$Arguments = @()
  )
  $stepRc = Invoke-HiddenPowerShellFile -FilePath $FilePath -Arguments $Arguments
  if ($stepRc -ne 0) {
    $cat = Get-AiosErrorCategory -ExitCode $stepRc -Stage $Stage
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "inv-morning" -Stage $Stage -Status "error" -ReturnCode $stepRc -EventDate $eventDate -Category $cat
  } else {
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "inv-morning" -Stage $Stage -Status "ok" -ReturnCode 0 -EventDate $eventDate -Category "ok"
  }
  return $stepRc
}

& $python "scripts/run_ops_scheduler.py" --slot inv-morning --date $eventDate
$rc = $LASTEXITCODE
if ($rc -eq 0 -and -not $isWeekend) {
  $stepRc = Invoke-AiosPostStep -FilePath "E:\workSpace\scripts\notify\resend_pending_discord.ps1" -Stage "resend_pending_discord.ps1" -Arguments @("-Limit", "5")
  if ($stepRc -ne 0) { $rc = $stepRc }
  $stepRc = Invoke-AiosPostStep -FilePath "E:\workSpace\scripts\notify\post_signal_quality_alert.ps1" -Stage "post_signal_quality_alert.ps1"
  if ($stepRc -ne 0) { $rc = $stepRc }
} elseif ($rc -eq 0 -and $isWeekend) {
  Write-Host "[skip] weekend post steps: inv-morning $eventDate"
}
exit $rc
