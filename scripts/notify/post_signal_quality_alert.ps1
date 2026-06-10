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

Load-EnvFile (Join-Path $repo ".env")

$webhook = $env:DISCORD_ALERT_WEBHOOK_URL
if (-not $webhook) { throw "DISCORD_ALERT_WEBHOOK_URL is empty" }

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
$reasonLabels = @{
  "CREDIT_THIN" = "信用情報が薄い"
  "DATA_THIN" = "シグナル件数が少ない"
  "MATERIAL_NONE_TODAY" = "当日材料がない"
  "MATERIAL_STALE" = "材料が古い"
  "NOON_DATA_GAP" = "昼のスナップショット不足"
  "REPEATED_TICKER_BIAS" = "同一銘柄の連続出現が多い"
  "SCENARIO_BIAS" = "有望シグナル配分が偏っている"
  "SIDE_IMBALANCE" = "上昇/下落方向の偏りが大きい"
}

function Format-ReasonCode([string]$code) {
  $k = [string]$code
  if ([string]::IsNullOrWhiteSpace($k)) { return "" }
  $label = $reasonLabels[$k]
  if ($label) {
    return ("{0}（{1}）" -f $k, $label)
  }
  return $k
}

$reasonLine = if ($reasonCodes.Count -gt 0) { ($reasonCodes | ForEach-Object { Format-ReasonCode $_ }) -join ", " } else { "なし" }
$root = if ($diag.inferredRootCause) { [string]$diag.inferredRootCause } else { "不明" }
$rootDisplay = Format-ReasonCode $root

$becomeCount = $diag.becomeScenarioCount
if ($null -eq $becomeCount) { $becomeCount = $diag.tradeScenarioCount }
$lines = @(
  ("シグナル品質アラート {0}" -f $Date),
  "- 判定: 警告",
  ("- 主因: {0}" -f $rootDisplay),
  ("- 理由コード: {0}" -f $reasonLine),
  ("- 要約: シグナル={0} 有望={1} 監視={2} 監視比率={3:P0}" -f $diag.signalCount, $becomeCount, $diag.watchScenarioCount, $watchShare)
)
if ($diag.alerts) {
  foreach ($a in $diag.alerts) {
    $lines += ("- 警告: " + [string]$a)
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
    $sent = Send-DiscordContent -WebhookUrl $webhook -Content ("AIOS シグナル品質アラート`n" + $msg) -WriteLog {
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
