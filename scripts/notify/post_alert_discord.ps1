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

$envFile = Join-Path $repo ".env"
if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match "^\s*#") { return }
    if ($_ -match "^\s*$") { return }
    if ($_ -notmatch "=") { return }
    $k,$v = $_.Split("=",2)
    $v = $v.Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($k.Trim(), $v, "Process")
  }
}

$u = $env:DISCORD_ALERT_WEBHOOK_URL
if (-not $u) {
  Write-AlertLog "SKIP" "DISCORD_ALERT_WEBHOOK_URL is empty"
  Write-Host "ALERT skipped (webhook empty)"
  exit 0
}

$statusPath = "E:\workSpace\prompts\pending-daily\latest.status.txt"
$clipPath   = "E:\workSpace\prompts\pending-daily\latest.clipboard.txt"
$schedPath  = "E:\workSpace\prompts\scheduler-health.status.txt"
$schedWeeklyPath = "E:\workSpace\prompts\scheduler-health-weekly.status.txt"

if (Test-Path $statusPath) {
  $status = [string](Get-Content $statusPath -Raw -Encoding UTF8)
} else {
  $status = "AIOS alert: status file not found."
}

$sched = ""
if (Test-Path $schedPath) {
  $sched = [string](Get-Content $schedPath -Raw -Encoding UTF8)
}
$schedWeekly = ""
if (Test-Path $schedWeeklyPath) {
  $schedWeekly = [string](Get-Content $schedWeeklyPath -Raw -Encoding UTF8)
}

$dailyOk = ($status -match "missing:\s*0" -or $status -match "AIOS daily OK")
$schedAlert = ($sched -match "status:\s*ALERT")
if ($dailyOk -and -not $schedAlert) {
  Write-AlertLog "SKIP" "no missing daily files and no scheduler alert"
  Write-Host "ALERT skipped (all healthy)"
  exit 0
}

$extra = ""
if (Test-Path $clipPath) {
  $extra = "`n`nPrompt file: prompts/pending-daily/latest.clipboard.txt"
}

$msg = "AIOS Alert`n" + $status.Trim()
if ($sched) {
  $msg += "`n`n---`n" + $sched.Trim()
}
if ($schedWeekly) {
  $msg += "`n`n---`n" + $schedWeekly.Trim()
}
$msg += $extra
$body = @{ content = $msg } | ConvertTo-Json -Compress -Depth 3

try {
  $maxAttempts = 3
  for ($attempt = 1; $attempt -le $maxAttempts; $attempt++) {
    try {
      Invoke-RestMethod -Method Post -Uri $u -ContentType "application/json; charset=utf-8" -Body $body | Out-Null
      Write-AlertLog "OK" ("posted attempt={0}" -f $attempt)
      Write-Host "ALERT posted"
      exit 0
    } catch {
      $respBody = ""
      if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $respBody = $reader.ReadToEnd()
        $reader.Close()
      }
      Write-AlertLog "ERROR" ("attempt={0}/{1} message={2} body={3}" -f $attempt, $maxAttempts, $_.Exception.Message, $respBody)
      if ($attempt -lt $maxAttempts) {
        Start-Sleep -Seconds (2 * $attempt)
        continue
      }
      throw
    }
  }
} catch {
  throw
}
