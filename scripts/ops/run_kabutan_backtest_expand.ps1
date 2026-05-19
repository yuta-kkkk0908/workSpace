Set-Location E:\workSpace
$py = "C:\Users\yuta_\AppData\Local\Programs\Python\Python312\python.exe"
$today = Get-Date -Format yyyy-MM-dd

& $py scripts\investment\collect\collect_kabutan_surprise_signals.py --date $today --sleep 1.5 --jitter 0.5 --discover-latest 12 --max-pages 24
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py scripts\investment\collect\collect_kabutan_short_signals.py --date $today --sleep 1.5 --jitter 0.5 --discover-latest 12 --max-pages 24
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py scripts\investment\backtest\fill_market_outcomes.py --date $today --seed-list rough_backtest_full
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $py scripts\investment\analysis\rule_check_market_outcomes.py --date $today --seed-list rough_backtest_full --min-count 20
exit $LASTEXITCODE
