$ErrorActionPreference = "Stop"

powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_discord_message.ps1" `
  -Repo "E:\workSpace" `
  -Kind "generic" `
  -MessagePath "E:\workSpace\prompts\generic-topics-discord-message.txt" `
  -PrimaryWebhookEnv "DISCORD_GENERIC_WEBHOOK_URL" `
  -FallbackWebhookEnv "DISCORD_ALERT_WEBHOOK_URL" `
  -HashFile "E:\workSpace\prompts\.last-generic-message.sha256.txt" `
  -UnchangedStreakFile "E:\workSpace\prompts\.generic-unchanged-streak.txt" `
  -UnchangedFailThreshold 3 `
  -PendingPrefix "generic" `
  -SkipIfUnchanged `
  -NotifyOnUnchanged `
  -AsEmbed `
  -SplitLimit 3500

exit $LASTEXITCODE
