param(
  [string]$Repo = "E:\workSpace",
  [int]$Limit = 20,
  [string[]]$Kinds = @()
)

$ErrorActionPreference = "Stop"

. (Join-Path $Repo "scripts\notify\discord_common.ps1")
Load-EnvFile (Join-Path $Repo ".env")

$pendingDir = Join-Path $Repo "prompts\pending"
if (-not (Test-Path $pendingDir)) {
  Write-Host "no pending dir"
  exit 0
}

$map = @{
  "generic" = "DISCORD_GENERIC_WEBHOOK_URL"
  "signal" = "DISCORD_SIGNAL_WEBHOOK_URL"
  "scenario" = "DISCORD_WEBHOOK_URL"
  "paper-stats" = "DISCORD_STATS_WEBHOOK_URL"
}
$hashFileMap = @{
  "generic" = "E:\workSpace\prompts\.last-generic-message.sha256.txt"
  "signal" = "E:\workSpace\prompts\.last-signal-message.sha256.txt"
  "paper-stats" = "E:\workSpace\prompts\.last-paper-stats-message.sha256.txt"
}
$fallbackMap = @{
  "generic" = "DISCORD_ALERT_WEBHOOK_URL"
  "signal" = "DISCORD_ALERT_WEBHOOK_URL"
  "scenario" = "DISCORD_ALERT_WEBHOOK_URL"
  "paper-stats" = "DISCORD_ALERT_WEBHOOK_URL"
}

$files = Get-ChildItem -Path $pendingDir -File -Filter "*-discord-pending-*.txt" | Sort-Object LastWriteTime
if ($Kinds -and $Kinds.Count -gt 0) {
  $want = @{}
  foreach ($k in $Kinds) {
    if ($null -ne $k -and "$k".Trim()) {
      $want["$k".Trim().ToLowerInvariant()] = $true
    }
  }
  $files = @($files | Where-Object {
    if ($_.Name -match "^(?<prefix>.+)-discord-pending-\d{8}-\d{6}\.txt$") {
      return $want.ContainsKey($Matches["prefix"].ToLowerInvariant())
    }
    return $false
  })
}
$files = @($files | Select-Object -First $Limit)
if (-not $files) {
  Write-Host "no pending files"
  exit 0
}

$ok = 0
$failed = 0
foreach ($f in $files) {
  if ($f.Name -notmatch "^(?<prefix>.+)-discord-pending-\d{8}-\d{6}\.txt$") {
    Write-Host "skip unknown pattern: $($f.Name)"
    continue
  }
  $prefix = $Matches["prefix"]
  if (-not $map.ContainsKey($prefix)) {
    Write-Host "skip unknown prefix: $prefix ($($f.Name))"
    continue
  }

  $msg = [string](Get-Content $f.FullName -Raw -Encoding UTF8)
  if ([string]::IsNullOrWhiteSpace($msg)) {
    Remove-Item -LiteralPath $f.FullName -Force
    Write-Host "deleted empty pending: $($f.Name)"
    continue
  }

  # De-dup: if the same message hash was already posted, drop pending without resend.
  if ($hashFileMap.ContainsKey($prefix)) {
    $hashFile = $hashFileMap[$prefix]
    if (Test-Path $hashFile) {
      $currentHash = Get-TextSha256 $msg
      $lastHash = (Get-Content $hashFile -Raw -Encoding UTF8).Trim()
      if ($currentHash -and $lastHash -and ($currentHash -eq $lastHash)) {
        Remove-Item -LiteralPath $f.FullName -Force
        Write-Host "deleted duplicate pending: $($f.Name)"
        continue
      }
    }
  }

  $primaryEnv = $map[$prefix]
  $primaryUrl = [Environment]::GetEnvironmentVariable($primaryEnv, "Process")
  if (-not $primaryUrl -and $prefix -eq "paper-stats") {
    $primaryUrl = [Environment]::GetEnvironmentVariable("DISCORD_SIGNAL_WEBHOOK_URL", "Process")
  }
  $fallbackUrl = [Environment]::GetEnvironmentVariable($fallbackMap[$prefix], "Process")
  if (-not $primaryUrl) {
    Write-Host ("missing webhook env for {0}: {1}" -f $prefix, $primaryEnv)
    $failed += 1
    continue
  }

  $asOf = $f.LastWriteTime.ToString("yyyy-MM-dd HH:mm")
  $msgToSend = "情報時点: ${asOf} JST`n" + $msg
  $parts = @(Split-ForDiscord $msgToSend 1800)
  $delivered = $true
  for ($i = 0; $i -lt $parts.Count; $i++) {
    $content = if ($parts.Count -gt 1) { "[{0}/{1}]`n{2}" -f ($i + 1), $parts.Count, $parts[$i] } else { $parts[$i] }
    $sent = Send-DiscordContent -WebhookUrl $primaryUrl -Content $content -WriteLog { param($level, $message) }
    if (-not $sent -and $fallbackUrl) {
      $fallbackContent = "[{0}-PENDING-RETRY] primary webhook unreachable.`n{1}" -f $prefix.ToUpperInvariant(), $content
      $sent = Send-DiscordContent -WebhookUrl $fallbackUrl -Content $fallbackContent -WriteLog { param($level, $message) }
    }
    if (-not $sent) {
      $delivered = $false
      break
    }
  }

  if ($delivered) {
    Remove-Item -LiteralPath $f.FullName -Force
    Write-Host "resent+deleted: $($f.Name)"
    $ok += 1
  } else {
    Write-Host "resend failed: $($f.Name)"
    $failed += 1
  }
}

Write-Host ("done ok={0} failed={1}" -f $ok, $failed)
exit 0
