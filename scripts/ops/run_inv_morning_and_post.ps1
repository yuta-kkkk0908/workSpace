powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Inv-Morning" `
  -CommandFile "E:\workSpace\scripts\ops\do_inv_morning_and_post.ps1"

