powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Night" `
  -CommandFile "E:\workSpace\scripts\ops\do_night_and_post_generic.ps1"

