$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

$python = "C:\msys64\usr\bin\python.exe"
if (-not (Test-Path $python)) {
  $python = Join-Path $repo ".venv\Scripts\python.exe"
}

$date = Get-Date -Format "yyyy-MM-dd"
& $python -X utf8 "scripts/notify/post_scenarios_bot.py" --date $date

exit $LASTEXITCODE
