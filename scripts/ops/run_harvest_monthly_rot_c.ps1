powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\run_harvest_window.ps1" `
  -Days 60 `
  -EndOffsetDays 121 `
  -TaskName "AIOS-Data-Harvest-Monthly-RotC"
