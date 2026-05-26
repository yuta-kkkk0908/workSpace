powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Tasks-Channel-Sync" `
  -CommandFile "E:\workSpace\scripts\ops\do_sync_tasks_channel.ps1"
