param(
  [string]$Date = (Get-Date -Format "yyyy-MM-dd")
)

$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "discord-signal-quality-alert.log"

. (Join-Path $repo "scripts\notify\discord_common.ps1")

function Write-QualityAlertLog([string]$level, [string]$message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "[$ts] [$level] $message" | Out-File -FilePath $logFile -Encoding utf8 -Append
}

function Format-ReasonCode([string]$code) {
  $k = [string]$code
  if ([string]::IsNullOrWhiteSpace($k)) { return "" }
  return $k
}

Load-EnvFile (Join-Path $repo ".env.local")

$webhook = $env:DISCORD_ALERT_WEBHOOK_URL
if ([string]::IsNullOrWhiteSpace($webhook)) {
  Write-QualityAlertLog "ERROR" "DISCORD_ALERT_WEBHOOK_URL is empty; skip signal quality alert"
  exit 0
}

$diagRaw = ""
$rcCheck = $null
$scriptPath = "scripts/investment/signals/check_signal_quality.py"
$candidates = @(
  "C:\msys64\usr\bin\python.exe",
  (Join-Path $repo ".venv\Scripts\python.exe"),
  "python",
  "python3"
)
$ran = $false
foreach ($exe in $candidates) {
  try {
    if ($exe -like "*\python.exe" -and -not (Test-Path $exe)) { continue }
    $env:PYTHONUTF8 = "1"
    $diagRaw = (& $exe -X utf8 $scriptPath --date $Date --print-json --no-write-files 2>$null | Out-String).Trim()
    $rcCheck = $LASTEXITCODE
    Write-QualityAlertLog "INFO" ("check_signal_quality exe={0} rc={1}" -f $exe, $rcCheck)
    $ran = $true
    break
  } catch {
    $err = $_.Exception.Message
    if ([string]::IsNullOrWhiteSpace($err) -or $err -match "^\?+$") {
      $err = "process_start_failed"
    }
    Write-QualityAlertLog "WARN" ("check_signal_quality exe={0} failed: {1}" -f $exe, $err)
  }
}
if (-not $ran) {
  Write-QualityAlertLog "ERROR" "check_signal_quality no python runtime available"
  exit 0
}

if ($rcCheck -ne 0 -and $rcCheck -ne 1) {
  Write-QualityAlertLog "ERROR" ("check_signal_quality unexpected rc={0}" -f $rcCheck)
  exit 0
}

if ([string]::IsNullOrWhiteSpace($diagRaw)) {
  Write-QualityAlertLog "ERROR" "empty diagnostics stdout"
  exit 0
}

try {
  $diag = $diagRaw | ConvertFrom-Json
} catch {
  Write-QualityAlertLog "ERROR" "failed to parse diagnostics json from stdout"
  exit 0
}

if ($diag.status -ne "ALERT") { exit 0 }

$watchShare = 0.0
try { if ($null -ne $diag.watchShare) { $watchShare = [double]$diag.watchShare } } catch { $watchShare = 0.0 }
$reasonCodes = @()
if ($diag.qualityReasonCodes) {
  $reasonCodes = @($diag.qualityReasonCodes | ForEach-Object { [string]$_ })
}
$reasonLine = if ($reasonCodes.Count -gt 0) { ($reasonCodes | ForEach-Object { Format-ReasonCode $_ }) -join ", " } else { "none" }
$root = if ($diag.inferredRootCause) { [string]$diag.inferredRootCause } else { "unknown" }
$becomeCount = $diag.becomeScenarioCount
if ($null -eq $becomeCount) { $becomeCount = $diag.tradeScenarioCount }

$lines = @(
  ("Signal quality alert {0}" -f $Date),
  "- status: ALERT",
  ("- root: {0}" -f $root),
  ("- reason_codes: {0}" -f $reasonLine),
  ("- summary: signals={0} become={1} watch={2} watch_share={3:P0}" -f $diag.signalCount, $becomeCount, $diag.watchScenarioCount, $watchShare)
)
if ($diag.alerts) {
  foreach ($a in $diag.alerts) {
    $lines += ("- alert: " + [string]$a)
  }
}
$msg = ($lines -join "`n").Trim()
if ([string]::IsNullOrWhiteSpace($msg)) { exit 0 }

$hashFile = "E:\workSpace\prompts\.last-signal-quality-alert.sha256.txt"
$hash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($msg))).Replace("-","").ToLower()
$last = if (Test-Path $hashFile) { (Get-Content $hashFile -Raw -Encoding UTF8).Trim() } else { "" }
if ($hash -eq $last) {
  Write-QualityAlertLog "SKIP" ("unchanged hash={0}" -f $hash)
  exit 0
}

Write-QualityAlertLog "START" ("msg_len={0}" -f $msg.Length)

$maxAttempts = 3
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
  try {
    $sent = Send-DiscordContent -WebhookUrl $webhook -Content ("AIOS Signal Quality Alert`n" + $msg) -WriteLog {
      param($level, $message)
      Write-QualityAlertLog $level $message
    } -MaxAttempts 1
    if (-not $sent) {
      throw "discord send failed"
    }
    Set-Content -Path $hashFile -Value $hash -Encoding UTF8
    Write-QualityAlertLog "OK" ("posted attempt={0} hash={1}" -f $attempt, $hash)
    exit 0
  } catch {
    Write-QualityAlertLog "ERROR" ("attempt={0}/{1} message={2}" -f $attempt, $maxAttempts, $_.Exception.Message)
    if ($attempt -lt $maxAttempts) {
      Start-Sleep -Seconds (2 * $attempt)
    } else {
      exit 0
    }
  }
}
