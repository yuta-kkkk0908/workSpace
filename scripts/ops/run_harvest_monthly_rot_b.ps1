powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\run_harvest_window.ps1" `
  -Days 60 `
  -EndOffsetDays 61 `
  -TaskName "AIOS-Data-Harvest-Monthly-RotB"
