$ErrorActionPreference = "Stop"

powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_discord_message.ps1" `
  -Repo "E:\workSpace" `
  -Kind "opskpi" `
  -MessagePath "E:\workSpace\prompts\ops-kpi-summary-discord-message.txt" `
  -PrimaryWebhookEnv "DISCORD_ALERT_WEBHOOK_URL" `
  -HashFile "E:\workSpace\prompts\.last-ops-kpi-message.sha256.txt" `
  -PendingPrefix "opskpi" `
  -SkipIfUnchanged `
  -SkipIfMessageMissing `
  -SkipIfMessageEmpty `
  -SplitLimit 3500

exit $LASTEXITCODE
