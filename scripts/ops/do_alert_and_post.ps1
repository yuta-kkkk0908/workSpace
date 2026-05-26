$ErrorActionPreference = "Stop"

. "E:\workSpace\scripts\ops\task_runner_common.ps1"

$rc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\ops\run_alert_healthcheck.ps1"
if ($rc -eq 0) {
  $rc = Invoke-HiddenPowerShellFile -FilePath "E:\workSpace\scripts\notify\post_alert_discord.ps1"
}
exit $rc
