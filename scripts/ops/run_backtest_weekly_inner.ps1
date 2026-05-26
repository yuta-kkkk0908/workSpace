$ErrorActionPreference = "Stop"
Set-Location "E:\workSpace"

$d = (Get-Date -Format yyyy-MM-dd)
$failedStep = ""

function Run-Step {
  param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][scriptblock]$Action
  )
  Write-Host ("[weekly] step={0} start" -f $Name)
  & $Action
  $rc = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
  if ($rc -ne 0) {
    $script:failedStep = $Name
    throw ("failed_step={0} rc={1}" -f $Name, $rc)
  }
  Write-Host ("[weekly] step={0} ok" -f $Name)
}

Run-Step -Name "run_backtest_suite_deep" -Action { py scripts/investment/backtest/run_backtest_suite.py --mode deep --date $d }
Run-Step -Name "init_investment_db" -Action { py scripts/data/init_investment_db.py }
Run-Step -Name "ingest_investment_db" -Action { py scripts/data/ingest_investment_db.py --date $d }
Run-Step -Name "analyze_exit_timing" -Action { py scripts/investment/backtest/analyze_exit_timing.py --out-date $d --mode all }
Run-Step -Name "analyze_paper_trade_stats" -Action { py scripts/investment/backtest/analyze_paper_trade_stats.py --out-date $d --mode all }
Run-Step -Name "analyze_watch_promotion" -Action { py scripts/investment/backtest/analyze_watch_promotion.py --out-date $d --ladder }
Run-Step -Name "generate_trade_watch_weekly_review" -Action { py scripts/investment/backtest/generate_trade_watch_weekly_review.py --out-date $d }
Run-Step -Name "fill_market_outcomes_full_weekly" -Action { py scripts/investment/backtest/fill_market_outcomes.py --date $d --seed-list rough_backtest_full }
Run-Step -Name "report_signal_type_coverage" -Action { py scripts/investment/analysis/report_signal_type_coverage.py --date $d --window-days 60 --min-material-count 8 --shortage-ratio 0.95 }

exit 0
