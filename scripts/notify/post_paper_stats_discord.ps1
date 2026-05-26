$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
. (Join-Path $repo "scripts\notify\discord_common.ps1")
Load-EnvFile (Join-Path $repo ".env")

$primary = [Environment]::GetEnvironmentVariable("DISCORD_STATS_WEBHOOK_URL", "Process")
if (-not $primary) {
  $primary = [Environment]::GetEnvironmentVariable("DISCORD_SIGNAL_WEBHOOK_URL", "Process")
}
if ($primary) {
  [Environment]::SetEnvironmentVariable("DISCORD_PAPER_STATS_ACTIVE_WEBHOOK_URL", $primary, "Process")
}

powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_discord_message.ps1" `
  -Repo "E:\workSpace" `
  -Kind "paper-stats" `
  -MessagePath "E:\workSpace\prompts\paper-stats-discord-message.txt" `
  -PrimaryWebhookEnv "DISCORD_PAPER_STATS_ACTIVE_WEBHOOK_URL" `
  -FallbackWebhookEnv "DISCORD_ALERT_WEBHOOK_URL" `
  -HashFile "E:\workSpace\prompts\.last-paper-stats-message.sha256.txt" `
  -UnchangedStreakFile "E:\workSpace\prompts\.paper-stats-unchanged-streak.txt" `
  -UnchangedFailThreshold 3 `
  -PendingPrefix "paper-stats" `
  -SkipIfUnchanged `
  -NotifyOnUnchanged `
  -SkipIfMessageMissing `
  -SkipIfMessageEmpty

exit $LASTEXITCODE
