$ErrorActionPreference = "Stop"

powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_discord_message.ps1" `
  -Repo "E:\workSpace" `
  -Kind "signal" `
  -MessagePath "E:\workSpace\prompts\market-signals-discord-message.txt" `
  -PrimaryWebhookEnv "DISCORD_SIGNAL_WEBHOOK_URL" `
  -FallbackWebhookEnv "DISCORD_ALERT_WEBHOOK_URL" `
  -HashFile "E:\workSpace\prompts\.last-signal-message.sha256.txt" `
  -UnchangedStreakFile "E:\workSpace\prompts\.signal-unchanged-streak.txt" `
  -UnchangedFailThreshold 3 `
  -PendingPrefix "signal" `
  -SkipIfUnchanged `
  -NotifyOnUnchanged

exit $LASTEXITCODE
