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

$path = "E:\workSpace\prompts\signal-quality-alert.txt"
if (-not (Test-Path $path)) { exit 0 }
$msg = (Get-Content $path -Raw -Encoding UTF8).Trim()
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
Write-QualityAlertLog "START" ("msg_len={0}" -f $msg.Length)
$maxAttempts = 3
for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
  try {
    Invoke-RestMethod -Method Post -Uri $u -ContentType "application/json; charset=utf-8" -Body $body | Out-Null
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
