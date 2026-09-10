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
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "inv-ai-2100" -Stage $Stage -Status "error" -ReturnCode $stepRc -EventDate $eventDate -Category $cat
  } else {
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "inv-ai-2100" -Stage $Stage -Status "ok" -ReturnCode 0 -EventDate $eventDate -Category "ok"
  }
  return $stepRc
}

$isDryRun = $false

& $python "scripts/run_ops_scheduler.py" --slot inv-evening --date $eventDate
$rc = $LASTEXITCODE

if ($rc -eq 0) {
  $stepRc = Invoke-AiosPostStep -FilePath "E:\workSpace\scripts\notify\resend_pending_discord.ps1" -Stage "resend_pending_discord.ps1" -Arguments @("-Limit", "5")
  if ($stepRc -ne 0) { $rc = $stepRc }
}

if ($rc -eq 0) {
  $aiArgs = @(
    "scripts/investment/analysis/generate_ai_investment_digest.py",
    "--date", $eventDate
  )
  if ($isDryRun) { $aiArgs += "--dry-run" }
  & $python @aiArgs
  $aiRc = $LASTEXITCODE
  if ($aiRc -ne 0) {
    Write-AiosPipelineEvent -Repo $repo -Pipeline "investment_analysis" -Slot "inv-ai-2100" -Stage "generate_ai_investment_digest.py" -Status "error" -ReturnCode $aiRc -EventDate $eventDate -Category "process_error"
    $rc = $aiRc
  } else {
    $mode = if ($isDryRun) { "dry-run" } else { "live" }
    Write-AiosPipelineEvent -Repo $repo -Pipeline "investment_analysis" -Slot "inv-ai-2100" -Stage "generate_ai_investment_digest.py" -Status "ok" -ReturnCode 0 -EventDate $eventDate -Category $mode
  }
}

if ($rc -ne 0) {
  $alertRc = Invoke-AiosPostStep -FilePath "E:\workSpace\scripts\notify\post_alert_discord.ps1" -Stage "post_alert_discord.ps1"
  if ($alertRc -ne 0) { $rc = $alertRc }
}

exit $rc
