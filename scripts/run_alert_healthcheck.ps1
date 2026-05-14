Set-Location "E:\workSpace"
py scripts/check_daily_missing.py --date today --days 7 *> $null
exit 0
