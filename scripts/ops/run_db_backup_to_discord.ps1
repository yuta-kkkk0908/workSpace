powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-DB-Backup-2230" `
  -Command 'Set-Location "E:\workSpace"; py scripts/data/backup_dbzip_to_discord.py --label investment-db-backup --keep-local 14; $LASTEXITCODE'
