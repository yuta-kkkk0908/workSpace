$ErrorActionPreference = "Stop"

$qualityFailThreshold = 0
try {
  $raw = [Environment]::GetEnvironmentVariable("DISCORD_SIGNAL_QUALITY_FAIL_THRESHOLD", "Process")
  if (-not [string]::IsNullOrWhiteSpace($raw)) {
    $parsed = 0
    if ([int]::TryParse($raw, [ref]$parsed)) {
      $qualityFailThreshold = [Math]::Max(0, $parsed)
    }
  }
} catch {
  $qualityFailThreshold = 0
}

powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_discord_message.ps1" `
  -Repo "E:\workSpace" `
  -Kind "signal" `
  -MessagePath "E:\workSpace\prompts\market-signals-discord-message.txt" `
  -PrimaryWebhookEnv "DISCORD_SIGNAL_WEBHOOK_URL" `
  -FallbackWebhookEnv "DISCORD_ALERT_WEBHOOK_URL" `
  -HashFile "E:\workSpace\prompts\.last-signal-message.sha256.txt" `
  -UnchangedStreakFile "E:\workSpace\prompts\.signal-unchanged-streak.txt" `
  -PendingPrefix "signal" `
  -SkipIfUnchanged `
  -NotifyOnUnchanged `
  -UnchangedFailThreshold $qualityFailThreshold

exit $LASTEXITCODE
