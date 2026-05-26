$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "discord-alert.log"

function Write-AlertLog([string]$level, [string]$message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "[$ts] [$level] $message" | Out-File -FilePath $logFile -Encoding utf8 -Append
}

Write-AlertLog "START" "post_alert_discord begin"
$python = "C:\msys64\usr\bin\python.exe"
if (-not (Test-Path $python)) {
  $python = Join-Path $repo ".venv\Scripts\python.exe"
}
if (-not (Test-Path $python)) {
  throw "python runtime not found"
}

& $python -X utf8 (Join-Path $repo "scripts\notify\post_alert_discord.py")
$rc = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
if ($rc -eq 0) {
  Write-AlertLog "OK" "python alert runner rc=0"
} else {
  Write-AlertLog "ERROR" ("python alert runner rc=" + $rc)
}
exit $rc
