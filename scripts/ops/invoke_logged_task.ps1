param(
  [Parameter(Mandatory=$true)][string]$TaskName,
  [string]$Command,
  [string]$CommandFile
)

$repo = "E:\workSpace"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "task-scheduler.log"
$preferredForegroundProcess = $env:AIOS_FOREGROUND_PROCESS
if ([string]::IsNullOrWhiteSpace($preferredForegroundProcess)) {
  $preferredForegroundProcess = "YourChronicle"
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class PowerKeepAwake {
  [Flags]
  public enum EXECUTION_STATE : uint {
    ES_AWAYMODE_REQUIRED = 0x00000040,
    ES_CONTINUOUS = 0x80000000,
    ES_DISPLAY_REQUIRED = 0x00000002,
    ES_SYSTEM_REQUIRED = 0x00000001
  }
  [DllImport("kernel32.dll", CharSet=CharSet.Auto, SetLastError=true)]
  public static extern EXECUTION_STATE SetThreadExecutionState(EXECUTION_STATE esFlags);
}
"@

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

function Get-LastTaskLevels([string]$taskName, [int]$tail = 500) {
  if (-not (Test-Path $logFile)) { return @() }
  $lines = Get-Content $logFile -Tail $tail -Encoding UTF8
  $levels = @()
  foreach ($line in $lines) {
    if ($line -notmatch ("\[$([regex]::Escape($taskName))\]")) { continue }
    if ($line -match "\[(START|OK|ERROR|EXCEPTION|END)\]") {
      $levels += $matches[1]
    }
  }
  return $levels
}

function Restore-ForegroundProcess([string]$processName) {
  if ([string]::IsNullOrWhiteSpace($processName)) { return $false }
  try {
    $proc = Get-Process -Name $processName -ErrorAction SilentlyContinue |
      Where-Object { $_.MainWindowHandle -ne 0 } |
      Sort-Object StartTime |
      Select-Object -First 1
    if (-not $proc) { return $false }
    $shell = New-Object -ComObject WScript.Shell
    return [bool]$shell.AppActivate([int]$proc.Id)
  } catch {
    return $false
  }
}

# Previous-run incomplete detection (best-effort): last START without END.
$levels = Get-LastTaskLevels -taskName $TaskName
if ($levels.Count -gt 0) {
  $lastStart = [Array]::LastIndexOf($levels, "START")
  $lastEnd = [Array]::LastIndexOf($levels, "END")
  if ($lastStart -gt $lastEnd) {
    Write-TaskLog "WARN" "previous run may be incomplete (last START has no END)"
  }
}

if ([string]::IsNullOrWhiteSpace($Command) -and [string]::IsNullOrWhiteSpace($CommandFile)) {
  throw "either -Command or -CommandFile is required"
}
if (-not [string]::IsNullOrWhiteSpace($Command) -and -not [string]::IsNullOrWhiteSpace($CommandFile)) {
  throw "specify only one of -Command or -CommandFile"
}

$startTarget = if (-not [string]::IsNullOrWhiteSpace($CommandFile)) {
  "file=" + $CommandFile
} else {
  "cmd=" + $Command
}
Write-TaskLog "START" ("begin " + $startTarget)
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$rc = 1
$keepAwakeSet = $false
try {
  # Prevent sleep while the command is running.
  [PowerKeepAwake]::SetThreadExecutionState([PowerKeepAwake+EXECUTION_STATE]::ES_CONTINUOUS -bor [PowerKeepAwake+EXECUTION_STATE]::ES_SYSTEM_REQUIRED) | Out-Null
  $keepAwakeSet = $true
  if (-not [string]::IsNullOrWhiteSpace($CommandFile)) {
    & $CommandFile
  } else {
    Invoke-Expression $Command
  }
  if ($null -ne $LASTEXITCODE) {
    $rc = [int]$LASTEXITCODE
  } elseif ($?) {
    $rc = 0
  } else {
    $rc = 1
  }
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
  if ($keepAwakeSet) {
    # Clear keep-awake request.
    [PowerKeepAwake]::SetThreadExecutionState([PowerKeepAwake+EXECUTION_STATE]::ES_CONTINUOUS) | Out-Null
  }
  if (Restore-ForegroundProcess -processName $preferredForegroundProcess) {
    Write-TaskLog "OK" ("foreground restored: " + $preferredForegroundProcess)
  }
  $sw.Stop()
  Write-TaskLog "END" ("elapsed_ms={0}" -f $sw.ElapsedMilliseconds)
}

exit $rc
