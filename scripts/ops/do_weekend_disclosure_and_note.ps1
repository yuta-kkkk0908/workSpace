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
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "disclosure-weekend" -Stage $Stage -Status "error" -ReturnCode $stepRc -EventDate $eventDate -Category $cat
  } else {
    Write-AiosPipelineEvent -Repo $repo -Pipeline "ops_post" -Slot "disclosure-weekend" -Stage $Stage -Status "ok" -ReturnCode 0 -EventDate $eventDate -Category "ok"
  }
  return $stepRc
}

$noteConfig = Join-Path $repo "configs\note.local.json"
$disclosureOutDir = Join-Path $repo "topics\investment-research\inbox"
$noteMarkdown = Join-Path $disclosureOutDir "$eventDate-note-ready.md"
$noteLog = Join-Path $repo "logs\disclosure-note-post-$eventDate.json"
$noteShot = Join-Path $repo "logs\disclosure-note-post-$eventDate.png"

$rc = Invoke-AiosDisclosureStep -Stage "run_morning_disclosure_digest.py" -Arguments @(
  "scripts/investment/analysis/run_morning_disclosure_digest.py",
  "--date", $eventDate,
  "--db", (Join-Path $repo "data\investment.db"),
  "--output-dir", $disclosureOutDir,
  "--limit", "20",
  "--lookback-days", "90",
  "--max-items", "120"
)
if ($rc -eq 0 -and (Test-Path $noteConfig)) {
  $stepRc = Invoke-AiosDisclosureStep -Stage "post_note_draft.py" -Arguments @(
    "scripts/notify/post_note_draft.py",
    "--markdown-path", $noteMarkdown,
    "--db", (Join-Path $repo "data\investment.db"),
    "--note-config", $noteConfig,
    "--log-path", $noteLog,
    "--screenshot-path", $noteShot
  )
  if ($stepRc -ne 0) { $rc = $stepRc }
} elseif ($rc -eq 0) {
  Write-Host "[skip] note draft post: config not found"
}

exit $rc
