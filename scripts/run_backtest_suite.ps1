Set-Location "E:\workSpace"

$date = Get-Date -Format yyyy-MM-dd
$mode = "quick"
$seed = ""
$minCount = 8

if ($args.Count -ge 1 -and $args[0]) { $mode = $args[0] }
if ($args.Count -ge 2 -and $args[1]) { $date = $args[1] }
if ($args.Count -ge 3 -and $args[2]) { $seed = $args[2] }
if ($args.Count -ge 4 -and $args[3]) { $minCount = [int]$args[3] }

$cmd = @("scripts/run_backtest_suite.py", "--mode", $mode, "--date", $date, "--min-count", "$minCount")
if ($seed -ne "") {
  $cmd += @("--seed-list", $seed)
}

py @cmd
exit $LASTEXITCODE
