param(
  [int]$Days = 30,
  [int]$EndOffsetDays = 1,
  [string]$TaskName = "AIOS-Data-Harvest-Window"
)

$endDate = (Get-Date).AddDays(-1 * [Math]::Max(0, $EndOffsetDays)).ToString("yyyy-MM-dd")
$cmd = "Set-Location `"E:\workSpace`"; py scripts/investment/collect/run_harvest_backfill.py --end-date $endDate --days $Days; `$LASTEXITCODE"

powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\ops\invoke_logged_task.ps1" `
  -TaskName $TaskName `
  -Command $cmd
