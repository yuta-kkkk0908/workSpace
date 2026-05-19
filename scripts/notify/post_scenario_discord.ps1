$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "discord-scenario.log"
function Write-ScenarioLog([string]$level, [string]$message) {
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

$u = $env:DISCORD_WEBHOOK_URL
if (-not $u) {
  Write-ScenarioLog "SKIP" "DISCORD_WEBHOOK_URL is empty"
  Write-Host "SCENARIO skipped (webhook empty)"
  exit 0
}

$msgPath = "E:\workSpace\prompts\opening-scenarios-discord-message.txt"
if (-not (Test-Path $msgPath)) {
  Write-ScenarioLog "SKIP" "message file not found: $msgPath"
  Write-Host "SCENARIO skipped (message file missing)"
  exit 0
}

$mObj = Get-Content $msgPath -Raw -Encoding UTF8
$m = [string]$mObj
if ([string]::IsNullOrWhiteSpace($m)) {
  Write-ScenarioLog "SKIP" "message is empty"
  Write-Host "SCENARIO skipped (empty message)"
  exit 0
}

$b = @{ content = $m } | ConvertTo-Json -Compress -Depth 3
try {
  Invoke-RestMethod -Method Post -Uri $u -ContentType "application/json; charset=utf-8" -Body $b | Out-Null
  Write-ScenarioLog "OK" "posted"
  Write-Host "SCENARIO posted"
} catch {
  $respBody = ""
  if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    $respBody = $reader.ReadToEnd()
    $reader.Close()
  }
  Write-ScenarioLog "ERROR" ("message={0} body={1}" -f $_.Exception.Message, $respBody)
  throw
}
