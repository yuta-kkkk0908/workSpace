$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

. (Join-Path $repo "scripts\ops\task_runner_common.ps1")
$python = Get-AiosPythonPath -Repo $repo

$d = Get-Date -Format yyyy-MM-dd
& $python "scripts/run_ops_scheduler.py" --slot night --date $d
$rc = $LASTEXITCODE
if ($rc -eq 0) {
  & $python "scripts/notify/render_ops_kpi_summary_discord_message.py" --date $d
  if ($LASTEXITCODE -ne 0) { $rc = $LASTEXITCODE }
  $stepRc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\notify\resend_pending_discord.ps1" -Arguments @("-Limit", "5")
  if ($stepRc -ne 0) { $rc = $stepRc }
  $envFile = Join-Path $repo ".env"
  if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
      if ($_ -match "^\s*#") { return }
      if ($_ -match "^\s*$") { return }
      if ($_ -notmatch "=") { return }
      $k,$v = $_.Split("=",2)
      [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim().Trim('"').Trim("'"), "Process")
    }
  }
  if ($env:DISCORD_GENERIC_FORUM_CHANNEL_ID) {
    $stepRc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\notify\post_generic_forum_discord.ps1"
    if ($stepRc -ne 0) { $rc = $stepRc }
  } else {
    Write-Host "[skip] DISCORD_GENERIC_FORUM_CHANNEL_ID is empty; skip generic discord post to avoid legacy thread path."
  }
  $stepRc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\notify\post_ops_kpi_discord.ps1"
  if ($stepRc -ne 0) { $rc = $stepRc }
}
exit $rc
