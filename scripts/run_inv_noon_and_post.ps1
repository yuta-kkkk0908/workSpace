powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\invoke_logged_task.ps1" `
  -TaskName "AIOS-Inv-Noon" `
  -Command 'Set-Location "E:\workSpace"; py scripts/run_ops_scheduler.py --slot inv-noon --date (Get-Date -Format yyyy-MM-dd); if ($LASTEXITCODE -eq 0) { powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\post_signal_discord.ps1" }; $LASTEXITCODE'
