powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Backtest-Weekly" `
  -Command 'Set-Location "E:\workSpace"; powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\run_backtest_weekly_inner.ps1"; $LASTEXITCODE'
