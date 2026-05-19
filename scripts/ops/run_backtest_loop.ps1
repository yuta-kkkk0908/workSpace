param(
  [string]$StartDate = "2026-04-01",
  [string]$EndDate = "2026-05-14",
  [int]$Lots = 1,
  [int]$MaxTrades = 3
)

Set-Location "E:\workSpace"

$start = Get-Date $StartDate
$end = Get-Date $EndDate
$current = $start

while ($current -le $end) {
  $date = $current.ToString("yyyy-MM-dd")
  Write-Host "=== backtest day: $date ==="

  py scripts\run_ops_scheduler.py --slot inv-morning --date $date --backtest
  if ($LASTEXITCODE -ne 0) { Write-Host "inv-morning failed: $date"; break }

  py scripts\run_ops_scheduler.py --slot inv-scenario --date $date --backtest
  if ($LASTEXITCODE -ne 0) { Write-Host "inv-scenario failed: $date"; break }

  py scripts\register_paper_trades.py --date $date --lots $Lots --max-trades $MaxTrades --mode backtest
  if ($LASTEXITCODE -ne 0) { Write-Host "register failed: $date"; break }

  py scripts\fill_paper_trade_outcomes.py --date $date --mode backtest --as-of $EndDate
  if ($LASTEXITCODE -ne 0) { Write-Host "fill outcomes failed: $date"; break }

  py scripts\report_paper_trades.py --date $date --mode backtest
  if ($LASTEXITCODE -ne 0) { Write-Host "report failed: $date"; break }

  $current = $current.AddDays(1)
}

py scripts\analyze_paper_trade_stats.py --mode backtest --start-date $StartDate --end-date $EndDate --out-date $EndDate
if ($LASTEXITCODE -ne 0) { Write-Host "stats failed" }

Write-Host "backtest loop done."
