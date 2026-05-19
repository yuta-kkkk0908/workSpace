param(
  [Parameter(Mandatory=$true)][string]$TaskName,
  [Parameter(Mandatory=$true)][string]$Command
)

$repo = "E:\workSpace"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "task-scheduler.log"

# Scheduled Task execution context often misses the Python launcher (`py`).
# If `py` is unavailable but `python` exists, alias `py` to `python`.
if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
  if (Get-Command python -ErrorAction SilentlyContinue) {
    Set-Alias -Name py -Value python -Scope Script
  }
}

function Write-TaskLog([string]$Level, [string]$Message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "[$ts] [$TaskName] [$Level] $Message" | Out-File -FilePath $logFile -Encoding utf8 -Append
}

Write-TaskLog "START" ("begin cmd=" + $Command)
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$rc = 1
try {
  Invoke-Expression $Command
  $rc = if ($null -ne $LASTEXITCODE) { [int]$LASTEXITCODE } else { 0 }
  if ($rc -eq 0) {
    Write-TaskLog "OK" "exit_code=0"
  } else {
    Write-TaskLog "ERROR" "exit_code=$rc"
  }
}
catch {
  $rc = 1
  Write-TaskLog "EXCEPTION" $_.Exception.Message
}
finally {
  $sw.Stop()
  Write-TaskLog "END" ("elapsed_ms={0}" -f $sw.ElapsedMilliseconds)
}

exit $rc
