$ErrorActionPreference = "Stop"

# Weekly recent 30 days (every Sunday 02:40)
schtasks /Create /TN "AIOS-Data-Harvest-Weekly-Recent30" /SC WEEKLY /D SUN /ST 02:40 /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\ops\run_harvest_weekly_recent30.ps1" /F | Out-Null
Write-Host "registered: AIOS-Data-Harvest-Weekly-Recent30"

# Weekly sample expansion (last 365 days, every Sunday 04:10)
schtasks /Create /TN "AIOS-Data-Harvest-Weekly-Samples365" /SC WEEKLY /D SUN /ST 04:10 /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\ops\run_harvest_weekly_samples365.ps1" /F | Out-Null
Write-Host "registered: AIOS-Data-Harvest-Weekly-Samples365"

# Monthly rotation (cover last 180 days by 60-day windows)
# RotA: 1st day
schtasks /Create /TN "AIOS-Data-Harvest-Monthly-RotA" /SC MONTHLY /D 1 /ST 03:00 /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\ops\run_harvest_monthly_rot_a.ps1" /F | Out-Null
Write-Host "registered: AIOS-Data-Harvest-Monthly-RotA"

# RotB: 11th day
schtasks /Create /TN "AIOS-Data-Harvest-Monthly-RotB" /SC MONTHLY /D 11 /ST 03:00 /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\ops\run_harvest_monthly_rot_b.ps1" /F | Out-Null
Write-Host "registered: AIOS-Data-Harvest-Monthly-RotB"

# RotC: 21st day
schtasks /Create /TN "AIOS-Data-Harvest-Monthly-RotC" /SC MONTHLY /D 21 /ST 03:00 /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File E:\workSpace\scripts\ops\run_harvest_monthly_rot_c.ps1" /F | Out-Null
Write-Host "registered: AIOS-Data-Harvest-Monthly-RotC"
