powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName "AIOS-Data-Harvest" `
  -Command 'Set-Location "E:\workSpace"; $d=(Get-Date -Format yyyy-MM-dd); py scripts/investment/collect/run_harvest_backfill.py --end-date $d --days 21 --discover-latest 120 --max-pages 120 --tdnet-max-items 800 --seed-list rough_backtest_full --max-signals 12 --max-long 6 --max-short 6; $LASTEXITCODE'
