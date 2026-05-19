$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "discord-paper-stats.log"
function Write-PaperStatsLog([string]$level, [string]$message) {
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

$u = $env:DISCORD_STATS_WEBHOOK_URL
if (-not $u) { $u = $env:DISCORD_SIGNAL_WEBHOOK_URL }
if (-not $u) { throw "DISCORD_STATS_WEBHOOK_URL or DISCORD_SIGNAL_WEBHOOK_URL is empty" }

$msgPath = "E:\workSpace\prompts\paper-stats-discord-message.txt"
if (-not (Test-Path $msgPath)) { throw "paper stats message file not found: $msgPath" }
$mObj = Get-Content $msgPath -Raw -Encoding UTF8
$m = [string]$mObj
if ([string]::IsNullOrWhiteSpace($m)) { throw "message is empty" }

$hashFile = "E:\workSpace\prompts\.last-paper-stats-message.sha256.txt"
$hash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($m))).Replace("-","").ToLower()
$last = if (Test-Path $hashFile) { (Get-Content $hashFile -Raw -Encoding UTF8).Trim() } else { "" }
if ($hash -eq $last) {
  Write-Host ("[{0}] PAPER_STATS: skipped (unchanged message)" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
  Write-PaperStatsLog "SKIP" ("unchanged hash={0}" -f $hash)
  exit 0
}

$payload = @{ content = $m }
$b = $payload | ConvertTo-Json -Compress -Depth 3
try {
  Invoke-RestMethod -Method Post -Uri $u -ContentType "application/json; charset=utf-8" -Body $b | Out-Null
} catch {
  $respBody = ""
  if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    $respBody = $reader.ReadToEnd()
    $reader.Close()
  }
  Write-PaperStatsLog "ERROR" ("message={0} body={1}" -f $_.Exception.Message, $respBody)
  throw
}

Set-Content -Path $hashFile -Value $hash -Encoding UTF8
Write-Host ("[{0}] PAPER_STATS: posted" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-PaperStatsLog "OK" ("posted hash={0}" -f $hash)
exit 0
