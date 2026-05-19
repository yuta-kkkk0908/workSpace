powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Night" `
  -Command 'Set-Location "E:\workSpace"; py scripts/run_ops_scheduler.py --slot night --date (Get-Date -Format yyyy-MM-dd); if ($LASTEXITCODE -eq 0) { powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_generic_discord.ps1"; if ($LASTEXITCODE -eq 0) { powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_signal_discord.ps1" } }; $LASTEXITCODE'
