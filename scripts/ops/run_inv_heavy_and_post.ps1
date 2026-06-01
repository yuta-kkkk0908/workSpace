powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Inv-Heavy-2000" `
  -CommandFile "E:\workSpace\scripts\ops\do_inv_heavy_and_post.ps1"
