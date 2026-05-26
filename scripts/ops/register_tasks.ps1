param(
  [string]$RepoPath = "E:\workSpace",
  [string]$PythonCmd = "py"
)

$ErrorActionPreference = "Stop"

function New-AiosTask {
  param(
    [string]$Name,
    [string]$TimeHHmm,
    [string]$ScriptPath,
    [string[]]$Days = @("Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday")
  )
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" -WorkingDirectory $RepoPath
  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -At $TimeHHmm
  $settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -Hidden
  Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
  Write-Host "registered: $Name ($TimeHHmm)"
}

New-AiosTask -Name "AIOS-Night" -TimeHHmm "21:00" -ScriptPath "$RepoPath\scripts\ops\run_night_and_post_generic.ps1"
New-AiosTask -Name "AIOS-Inv-Morning" -TimeHHmm "07:30" -ScriptPath "$RepoPath\scripts\ops\run_inv_morning_and_post.ps1"
New-AiosTask -Name "AIOS-Inv-Noon" -TimeHHmm "12:10" -ScriptPath "$RepoPath\scripts\ops\run_inv_noon_and_post.ps1"
New-AiosTask -Name "AIOS-Inv-Evening" -TimeHHmm "21:10" -ScriptPath "$RepoPath\scripts\ops\run_inv_evening_and_post.ps1"
New-AiosTask -Name "AIOS-Inv-Scenario-0810" -TimeHHmm "08:10" -ScriptPath "$RepoPath\scripts\ops\run_inv_scenario_and_post.ps1" -Days @("Monday","Tuesday","Wednesday","Thursday","Friday")
New-AiosTask -Name "AIOS-Alert-Healthcheck" -TimeHHmm "21:20" -ScriptPath "$RepoPath\scripts\ops\run_alert_and_post.ps1"
New-AiosTask -Name "AIOS-Backtest-Weekly" -TimeHHmm "03:30" -ScriptPath "$RepoPath\scripts\ops\run_backtest_weekly.ps1" -Days @("Sunday")
New-AiosTask -Name "AIOS-Data-Harvest" -TimeHHmm "23:40" -ScriptPath "$RepoPath\scripts\ops\run_data_harvest.ps1"

# Scenario reply sync windows: every 5 minutes for 1 hour
# Morning window: 09:00-10:00
$syncCmd = "powershell.exe -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$RepoPath\scripts\ops\run_sync_scenario_replies.ps1`""
schtasks /Create /TN "AIOS-Scenario-Replies-Sync-Morning" /SC DAILY /ST 09:00 /RI 5 /DU 01:00 /TR $syncCmd /F | Out-Null
Write-Host "registered: AIOS-Scenario-Replies-Sync-Morning (09:00-10:00 / every 5m)"

# Noon window: 12:30-13:30
schtasks /Create /TN "AIOS-Scenario-Replies-Sync-Noon" /SC DAILY /ST 12:30 /RI 5 /DU 01:00 /TR $syncCmd /F | Out-Null
Write-Host "registered: AIOS-Scenario-Replies-Sync-Noon (12:30-13:30 / every 5m)"

# Manual-run only helper task (run on demand from Task Scheduler UI)
schtasks /Create /TN "AIOS-Scenario-Replies-Sync-Manual" /SC ONCE /ST 00:00 /SD 2099/01/01 /TR $syncCmd /F | Out-Null
Write-Host "registered: AIOS-Scenario-Replies-Sync-Manual (on-demand)"

Get-ScheduledTask -TaskName "AIOS-Night","AIOS-Inv-Morning","AIOS-Inv-Noon","AIOS-Inv-Evening","AIOS-Inv-Scenario-0810","AIOS-Alert-Healthcheck","AIOS-Backtest-Weekly","AIOS-Data-Harvest","AIOS-Scenario-Replies-Sync-Morning","AIOS-Scenario-Replies-Sync-Noon","AIOS-Scenario-Replies-Sync-Manual" -ErrorAction SilentlyContinue |
  Select-Object TaskName,State
