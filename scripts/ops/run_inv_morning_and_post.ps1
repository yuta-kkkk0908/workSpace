powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Inv-Morning" `
  -Command 'Set-Location "E:\workSpace"; py scripts/run_ops_scheduler.py --slot inv-morning --date (Get-Date -Format yyyy-MM-dd); if ($LASTEXITCODE -eq 0) { powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_signal_discord.ps1"; powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_signal_quality_alert.ps1" }; $LASTEXITCODE'
