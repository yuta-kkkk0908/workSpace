$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
. (Join-Path $repo "scripts\notify\discord_common.ps1")
Load-EnvFile (Join-Path $repo ".env.local")

$primary = [Environment]::GetEnvironmentVariable("DISCORD_STATS_WEBHOOK_URL", "Process")
if (-not $primary) {
  $primary = [Environment]::GetEnvironmentVariable("DISCORD_SIGNAL_WEBHOOK_URL", "Process")
}
if ($primary) {
  [Environment]::SetEnvironmentVariable("DISCORD_EXIT_ANALYZER_ACTIVE_WEBHOOK_URL", $primary, "Process")
}

powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_discord_message.ps1" `
  -Repo "E:\workSpace" `
  -Kind "exit-analyzer" `
  -MessagePath "E:\workSpace\tmp\prompts\exit-analyzer-discord-message.txt" `
  -PrimaryWebhookEnv "DISCORD_EXIT_ANALYZER_ACTIVE_WEBHOOK_URL" `
  -FallbackWebhookEnv "DISCORD_ALERT_WEBHOOK_URL" `
  -HashFile "E:\workSpace\tmp\prompts\.last-exit-analyzer-message.sha256.txt" `
  -UnchangedStreakFile "E:\workSpace\tmp\prompts\.exit-analyzer-unchanged-streak.txt" `
  -UnchangedFailThreshold 3 `
  -PendingPrefix "exit-analyzer" `
  -SkipIfUnchanged `
  -NotifyOnUnchanged `
  -SkipIfMessageMissing `
  -SkipIfMessageEmpty

exit $LASTEXITCODE
