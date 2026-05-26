powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Inv-Noon" `
  -CommandFile "E:\workSpace\scripts\ops\do_inv_noon_and_post.ps1"

