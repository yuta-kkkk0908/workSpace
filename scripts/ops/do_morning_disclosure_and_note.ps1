$ErrorActionPreference = "Stop"

$repo = "E:\workSpace"
Set-Location $repo

. (Join-Path $repo "scripts\ops\task_runner_common.ps1")
$python = Get-AiosPythonPath -Repo $repo
$eventDate = Get-Date -Format yyyy-MM-dd

function Invoke-AiosDisclosureStep {
  param(
    [string]$Stage,
    [string[]]$Arguments
  )
  $stepRc = & $python @Arguments
  if ($null -ne $LASTEXITCODE) {
    $stepRc = [int]$LASTEXITCODE
  }
  if ($stepRc -ne 0) {
    $cat = Get-AiosErrorCategory -ExitCode $stepRc -Stage $Stage
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "disclosure-morning" -Stage $Stage -Status "error" -ReturnCode $stepRc -EventDate $eventDate -Category $cat
  } else {
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "disclosure-morning" -Stage $Stage -Status "ok" -ReturnCode 0 -EventDate $eventDate -Category "ok"
  }
  return $stepRc
}

$disclosureOutDir = Join-Path $repo "topics\investment-research\inbox"

$rc = Invoke-AiosDisclosureStep -Stage "run_morning_disclosure_digest.py" -Arguments @(
  "scripts/investment/analysis/run_morning_disclosure_digest.py",
  "--date", $eventDate,
  "--db", (Join-Path $repo "data\investment.db"),
  "--output-dir", $disclosureOutDir,
  "--limit", "20",
  "--lookback-days", "90",
  "--max-items", "120"
)
if ($rc -eq 0) {
  Write-Host "[disabled] note draft post"
}

exit $rc
