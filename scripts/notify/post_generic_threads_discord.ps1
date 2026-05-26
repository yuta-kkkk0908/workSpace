$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

$python = "C:\msys64\usr\bin\python.exe"
if (-not (Test-Path $python)) {
  $python = Join-Path $repo ".venv\Scripts\python.exe"
}

& $python -X utf8 "scripts/notify/post_generic_threads_bot.py"
exit $LASTEXITCODE
