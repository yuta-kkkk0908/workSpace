powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Alert-Healthcheck" `
  -CommandFile "E:\workSpace\scripts\ops\do_alert_and_post.ps1"
