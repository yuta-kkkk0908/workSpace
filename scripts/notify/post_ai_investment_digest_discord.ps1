$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
$python = "C:\msys64\usr\bin\python.exe"
if (-not (Test-Path $python)) {
  $python = Join-Path $repo ".venv\Scripts\python.exe"
}
if (Test-Path $python) {
  & $python "E:\workSpace\scripts\notify\render_ai_investment_digest_from_db.py" --date (Get-Date -Format "yyyy-MM-dd")
}

powershell -NoProfile -ExecutionPolicy Bypass -File "E:\workSpace\scripts\notify\post_discord_message.ps1" `
  -Repo $repo `
  -Kind "ai-investment-digest" `
  -MessagePath "E:\workSpace\prompts\ai-investment-digest.txt" `
  -PrimaryWebhookEnv "DISCORD_SIGNAL_WEBHOOK_URL" `
  -FallbackWebhookEnv "DISCORD_ALERT_WEBHOOK_URL" `
  -HashFile "E:\workSpace\prompts\.last-ai-investment-digest.sha256.txt" `
  -PendingPrefix "ai-investment-digest" `
  -SkipIfUnchanged

exit $LASTEXITCODE
