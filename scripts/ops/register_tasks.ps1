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
  $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" -WorkingDirectory $RepoPath
  $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Days -At $TimeHHmm
  $settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable
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

Get-ScheduledTask -TaskName "AIOS-Night","AIOS-Inv-Morning","AIOS-Inv-Noon","AIOS-Inv-Evening","AIOS-Inv-Scenario-0810","AIOS-Alert-Healthcheck","AIOS-Backtest-Weekly" |
  Select-Object TaskName,State
