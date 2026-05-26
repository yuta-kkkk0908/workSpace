powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\run_harvest_window.ps1" `
  -Days 30 `
  -EndOffsetDays 1 `
  -TaskName "AIOS-Data-Harvest-Weekly-Recent30"
