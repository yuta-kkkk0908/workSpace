powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\invoke_logged_task.ps1" `
  -TaskName "AIOS-Inv-Scenario-0810" `
  -Command 'Set-Location "E:\workSpace"; py scripts/run_ops_scheduler.py --slot inv-scenario --date (Get-Date -Format yyyy-MM-dd); if ($LASTEXITCODE -eq 0) { powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\post_scenario_discord.ps1" }; $LASTEXITCODE'
