$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "discord-generic.log"
function Write-GenericLog([string]$level, [string]$message) {
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

$u = $env:DISCORD_GENERIC_WEBHOOK_URL
if (-not $u) { throw "DISCORD_GENERIC_WEBHOOK_URL is empty" }

$msgPath = "E:\workSpace\prompts\generic-topics-discord-message.txt"
if (-not (Test-Path $msgPath)) { throw "generic message file not found: $msgPath" }
$m = Get-Content $msgPath -Raw -Encoding UTF8
if ([string]::IsNullOrWhiteSpace($m)) { throw "message is empty" }

function Split-ForDiscord([string]$text, [int]$limit = 1800) {
  $lines = ($text -replace "`r`n","`n") -split "`n"
  $chunks = @()
  $buf = ""
  foreach ($line in $lines) {
    $cand = if ($buf) { "$buf`n$line" } else { $line }
    if ($cand.Length -le $limit) { $buf = $cand; continue }
    if ($buf) { $chunks += $buf }
    if ($line.Length -le $limit) {
      $buf = $line
    } else {
      for ($i=0; $i -lt $line.Length; $i += $limit) {
        $len = [Math]::Min($limit, $line.Length - $i)
        $chunks += $line.Substring($i, $len)
      }
      $buf = ""
    }
  }
  if ($buf) { $chunks += $buf }
  return $chunks
}

$parts = @(Split-ForDiscord $m 1800)
Write-GenericLog "START" ("parts={0} msg_len={1}" -f $parts.Count, $m.Length)
for ($i=0; $i -lt $parts.Count; $i++) {
  $content = if ($parts.Count -gt 1) { "[{0}/{1}]`n{2}" -f ($i+1), $parts.Count, $parts[$i] } else { $parts[$i] }
  $b = @{ content = $content } | ConvertTo-Json -Compress -Depth 3
  try {
    Invoke-RestMethod -Method Post -Uri $u -ContentType "application/json; charset=utf-8" -Body $b | Out-Null
  }
  catch {
    $resp = $_.Exception.Response
    if ($resp) {
      $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
      $body = $sr.ReadToEnd()
      Write-GenericLog "ERROR" ("part={0}/{1} message={2} body={3}" -f ($i+1), $parts.Count, $_.Exception.Message, $body)
      throw "discord generic post failed: $body"
    }
    Write-GenericLog "ERROR" ("part={0}/{1} message={2}" -f ($i+1), $parts.Count, $_.Exception.Message)
    throw
  }
}

Write-Host ("GENERIC posted parts={0}" -f $parts.Count)
Write-GenericLog "OK" ("posted parts={0}" -f $parts.Count)
