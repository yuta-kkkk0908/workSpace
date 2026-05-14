$repo = "E:\workSpace"
$envFile = Join-Path $repo ".env"

if (Test-Path $envFile) {
  Get-Content $envFile | ForEach-Object {
    if ($_ -match "^\s*#") { return }
    if ($_ -match "^\s*$") { return }
    $k,$v = $_.Split("=",2)
    [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
  }
}

$u = $env:DISCORD_ALERT_WEBHOOK_URL
if (-not $u) { throw "DISCORD_ALERT_WEBHOOK_URL is empty" }

$statusPath = "E:\workSpace\prompts\pending-daily\latest.status.txt"
$clipPath   = "E:\workSpace\prompts\pending-daily\latest.clipboard.txt"

if (Test-Path $statusPath) {
  $status = Get-Content $statusPath -Raw -Encoding UTF8
} else {
  $status = "AIOS alert: status file not found."
}

# 欠損がある時だけ送信したい場合
if ($status -match "missing:\s+0") {
  exit 0
}

$extra = ""
if (Test-Path $clipPath) {
  $extra = "`n`n補完プロンプト: prompts/pending-daily/latest.clipboard.txt"
}

$msg = "AIOS Alert`n" + $status.Trim() + $extra
$body = @{ content = $msg } | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri $u -ContentType "application/json" -Body $body | Out-Null
