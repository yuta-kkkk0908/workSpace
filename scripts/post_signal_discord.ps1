$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "discord-signal.log"
function Write-SignalLog([string]$level, [string]$message) {
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

$u = $env:DISCORD_SIGNAL_WEBHOOK_URL
if (-not $u) { throw "DISCORD_SIGNAL_WEBHOOK_URL is empty" }

$m = Get-Content "E:\workSpace\prompts\market-signals-discord-message.txt" -Raw -Encoding UTF8
if ([string]::IsNullOrWhiteSpace($m)) { throw "message is empty" }

# 同文投稿スキップ
$hashFile = "E:\workSpace\prompts\.last-signal-message.sha256.txt"
$hash = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($m))).Replace("-","").ToLower()
$last = if (Test-Path $hashFile) { (Get-Content $hashFile -Raw -Encoding UTF8).Trim() } else { "" }
if ($hash -eq $last) {
  $msg = ("[{0}] SIGNAL: skipped (unchanged message)" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
  Write-Host $msg
  Write-SignalLog "SKIP" ("unchanged hash={0}" -f $hash)
  exit 0
}
function Split-ForDiscord([string]$text, [int]$limit = 1800) {
  $lines = ($text -replace "`r`n","`n") -split "`n"
  $chunks = @(); $buf = ""
  foreach ($line in $lines) {
    $cand = if ($buf) { "$buf`n$line" } else { $line }
    if ($cand.Length -le $limit) { $buf = $cand; continue }
    if ($buf) { $chunks += $buf }
    if ($line.Length -le $limit) { $buf = $line } else {
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
Write-SignalLog "START" ("parts={0} msg_len={1}" -f $parts.Count, $m.Length)
for ($i=0; $i -lt $parts.Count; $i++) {
  $content = if ($parts.Count -gt 1) { "[{0}/{1}]`n{2}" -f ($i+1), $parts.Count, $parts[$i] } else { $parts[$i] }
  $b = @{ content = $content } | ConvertTo-Json -Compress
  try {
    Invoke-RestMethod -Method Post -Uri $u -ContentType "application/json; charset=utf-8" -Body $b | Out-Null
  } catch {
    $respBody = ""
    if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
      $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
      $respBody = $reader.ReadToEnd()
      $reader.Close()
    }
    Write-SignalLog "ERROR" ("part={0}/{1} message={2} body={3}" -f ($i+1), $parts.Count, $_.Exception.Message, $respBody)
    throw
  }
}
Set-Content -Path $hashFile -Value $hash -Encoding UTF8
Write-Host ("[{0}] SIGNAL: posted parts={1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $parts.Count)
Write-SignalLog "OK" ("posted parts={0} hash={1}" -f $parts.Count, $hash)
exit 0

