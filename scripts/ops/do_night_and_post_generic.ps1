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
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "night" -Stage $Stage -Status "error" -ReturnCode $stepRc -EventDate $eventDate -Category $cat
  } else {
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "night" -Stage $Stage -Status "ok" -ReturnCode 0 -EventDate $eventDate -Category "ok"
  }
  return $stepRc
}

$d = $eventDate
& $python "scripts/run_ops_scheduler.py" --slot night --date $d
$rc = $LASTEXITCODE
if ($rc -eq 0) {
  & $python "scripts/notify/render_ops_kpi_summary_discord_message.py" --date $d
  if ($LASTEXITCODE -ne 0) { $rc = $LASTEXITCODE }
  $stepRc = Invoke-AiosPostStep -FilePath "E:\workSpace\scripts\notify\resend_pending_discord.ps1" -Stage "resend_pending_discord.ps1" -Arguments @("-Limit", "5")
  if ($stepRc -ne 0) { $rc = $stepRc }
  foreach ($envFile in @((Join-Path $repo ".env"), (Join-Path $repo ".env.local"))) {
    if (-not (Test-Path $envFile)) { continue }
    foreach ($line in Get-Content $envFile) {
      if ($line -match "^\s*#") { continue }
      if ($line -match "^\s*$") { continue }
      if ($line -notmatch "=") { continue }
      $k,$v = $line.Split("=",2)
      [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim().Trim('"').Trim("'"), "Process")
    }
  }
  if ($env:DISCORD_GENERIC_FORUM_CHANNEL_ID) {
    $stepRc = Invoke-AiosPostStep -FilePath "E:\workSpace\scripts\notify\post_generic_forum_discord.ps1" -Stage "post_generic_forum_discord.ps1"
    if ($stepRc -ne 0) { $rc = $stepRc }
  } else {
    Write-Host "[skip] DISCORD_GENERIC_FORUM_CHANNEL_ID is empty; skip generic discord post to avoid legacy thread path."
  }
  $stepRc = Invoke-AiosPostStep -FilePath "E:\workSpace\scripts\notify\post_ops_kpi_discord.ps1" -Stage "post_ops_kpi_discord.ps1"
  if ($stepRc -ne 0) { $rc = $stepRc }
}
exit $rc
