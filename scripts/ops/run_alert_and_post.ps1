powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Alert-Healthcheck" `
  -Command 'powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\run_alert_healthcheck.ps1"; $rc = $LASTEXITCODE; if ($rc -eq 0) { powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_alert_discord.ps1"; $rc = $LASTEXITCODE }; $rc'
