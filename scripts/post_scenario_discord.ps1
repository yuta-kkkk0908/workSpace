$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
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
if (-not $u) { throw "DISCORD_WEBHOOK_URL is empty" }
$m = Get-Content "E:\workSpace\prompts\opening-scenarios-discord-message.txt" -Raw -Encoding UTF8
if ([string]::IsNullOrWhiteSpace($m)) { throw "message is empty" }
$b = @{ content = $m } | ConvertTo-Json -Compress -Depth 3
Invoke-RestMethod -Method Post -Uri $u -ContentType "application/json; charset=utf-8" -Body $b | Out-Null
Write-Host "SCENARIO posted"
