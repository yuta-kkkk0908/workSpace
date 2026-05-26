param(
  [string]$Date = (Get-Date -Format "yyyy-MM-dd")
)

$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "discord-signal-quality-alert.log"
function Write-QualityAlertLog([string]$level, [string]$message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "[$ts] [$level] $message" | Out-File -FilePath $logFile -Encoding utf8 -Append
}

$envFile = Join-Path $repo ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match "^\s*#") { return }
    if ($_ -match "^\s*$") { return }
    $k,$v = $_.Split("=",2)
    $v = $v.Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($k.Trim(), $v, "Process")
  }
}

$u = $env:DISCORD_ALERT_WEBHOOK_URL
if (-not $u) { throw "DISCORD_ALERT_WEBHOOK_URL is empty" }

# DB-first: fetch diagnostics JSON from script stdout (no runtime file dependency).
$diagRaw = ""
try {
  $checkScript = Join-Path $repo "scripts\investment\signals\check_signal_quality.py"
  $env:PYTHONUTF8 = "1"
  $diagRaw = (& py -X utf8 $checkScript --date $Date --print-json --no-write-files 2>$null | Out-String).Trim()
  $rcCheck = $LASTEXITCODE
  Write-QualityAlertLog "INFO" ("check_signal_quality rc={0}" -f $rcCheck)
} catch {
  Write-QualityAlertLog "ERROR" ("check_signal_quality failed: {0}" -f $_.Exception.Message)
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

$alerts = @()
if ($diag.alerts) {
  foreach ($a in $diag.alerts) { $alerts += "- $a" }
}
$holdBreak = ""
if ($diag.gateHoldBreakdown) {
  $pairs = @()
  foreach ($p in $diag.gateHoldBreakdown.PSObject.Properties) {
    $pairs += ("{0}={1}" -f $p.Name, $p.Value)
  }
  if ($pairs.Count -gt 0) { $holdBreak = "- holdBreakdown: " + ($pairs -join ", ") }
}
$root = ""
if ($null -ne $diag.inferredRootCause) { $root = [string]$diag.inferredRootCause }
$watchShare = 0.0
if ($null -ne $diag.watchShare) {
  try { $watchShare = [double]$diag.watchShare } catch { $watchShare = 0.0 }
}

$lines = @(
  ("Signal Quality Alert {0}" -f $Date),
  "- status: ALERT",
  ("- inferredRootCause: {0}" -f $root),
  ("- summary: signals={0} trade={1} watch={2} watchShare={3:P0}" -f $diag.signalCount, $diag.tradeScenarioCount, $diag.watchScenarioCount, $watchShare)
)
if ($alerts.Count -gt 0) { $lines += $alerts }
if ($holdBreak) { $lines += $holdBreak }
$msg = ($lines -join "`n")
$msg = $msg.Trim()
if ([string]::IsNullOrWhiteSpace($msg)) { exit 0 }

# same message skip
$hashFile = "E:\workSpace\prompts\.last-signal-quality-alert.sha256.txt"
$hash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($msg))).Replace("-","").ToLower()
$last = if (Test-Path $hashFile) { (Get-Content $hashFile -Raw -Encoding UTF8).Trim() } else { "" }
if ($hash -eq $last) {
  Write-Host "quality alert unchanged; skip"
  Write-QualityAlertLog "SKIP" ("unchanged hash={0}" -f $hash)
  exit 0
}

$body = @{ content = ("AIOS Signal Quality Alert`n" + $msg) } | ConvertTo-Json -Compress
$bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
Write-QualityAlertLog "START" ("msg_len={0}" -f $msg.Length)
$maxAttempts = 3
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
  try {
    Invoke-RestMethod -Method Post -Uri $u -ContentType "application/json; charset=utf-8" -Body $bodyBytes | Out-Null
    Set-Content -Path $hashFile -Value $hash -Encoding UTF8
    Write-Host "quality alert posted"
    Write-QualityAlertLog "OK" ("posted attempt={0} hash={1}" -f $attempt, $hash)
    exit 0
  } catch {
    $respBody = ""
    if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
      $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
      $respBody = $reader.ReadToEnd()
      $reader.Close()
    }
    Write-QualityAlertLog "ERROR" ("attempt={0}/{1} message={2} body={3}" -f $attempt, $maxAttempts, $_.Exception.Message, $respBody)
    if ($attempt -lt $maxAttempts) {
      Start-Sleep -Seconds (2 * $attempt)
      continue
    }
    throw
  }
}
