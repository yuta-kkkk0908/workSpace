$ErrorActionPreference = "Continue"

$repo = "E:\workSpace"
$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "alert-healthcheck.log"
function Write-AlertHealthLog([string]$level, [string]$message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "[$ts] [$level] $message" | Out-File -FilePath $logFile -Encoding utf8 -Append
}

Set-Location $repo

$cmds = @(
  @("py", "scripts/check_daily_missing.py", "--date", "today", "--days", "7", "--check-db", "--check-discord-posts", "--warn-only-soft"),
  @("python", "scripts/check_daily_missing.py", "--date", "today", "--days", "7", "--check-db", "--check-discord-posts", "--warn-only-soft"),
  @("python3", "scripts/check_daily_missing.py", "--date", "today", "--days", "7", "--check-db", "--check-discord-posts", "--warn-only-soft")
)

$ok = $false
foreach ($c in $cmds) {
  $exe = $c[0]
  $args = $c[1..($c.Length-1)]
  try {
    & $exe @args *> $null
    if ($LASTEXITCODE -eq 0) {
      Write-AlertHealthLog "OK" ("checker ran via {0} exit=0" -f $exe)
      $ok = $true
      break
    } elseif ($LASTEXITCODE -eq 1) {
      # check_daily_missing returns 1 when missing/hard warnings are detected.
      # This is a valid run result for healthcheck and should not be treated as execution failure.
      Write-AlertHealthLog "WARN" ("checker ran via {0} exit=1 (alerts detected)" -f $exe)
      $ok = $true
      break
    } else {
      Write-AlertHealthLog "WARN" ("checker failed via {0} exit={1}" -f $exe, $LASTEXITCODE)
    }
  } catch {
    Write-AlertHealthLog "WARN" ("checker exception via {0}: {1}" -f $exe, $_.Exception.Message)
  }
}

if (-not $ok) {
  Write-AlertHealthLog "WARN" "checker unavailable; continue without failing task"
}

$healthCmds = @(
  @("py", "scripts/check_scheduler_health.py", "--mode", "daily", "--hours", "48"),
  @("python", "scripts/check_scheduler_health.py", "--mode", "daily", "--hours", "48"),
  @("python3", "scripts/check_scheduler_health.py", "--mode", "daily", "--hours", "48")
)

$healthOk = $false
foreach ($c in $healthCmds) {
  $exe = $c[0]
  $args = $c[1..($c.Length-1)]
  try {
    & $exe @args *> $null
    if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq 2) {
      Write-AlertHealthLog "OK" ("scheduler-health ran via {0} exit={1}" -f $exe, $LASTEXITCODE)
      $healthOk = $true
      break
    } else {
      Write-AlertHealthLog "WARN" ("scheduler-health failed via {0} exit={1}" -f $exe, $LASTEXITCODE)
    }
  } catch {
    Write-AlertHealthLog "WARN" ("scheduler-health exception via {0}: {1}" -f $exe, $_.Exception.Message)
  }
}

if (-not $healthOk) {
  Write-AlertHealthLog "WARN" "scheduler-health unavailable; continue without failing task"
}

# Weekly detail report (run on Monday JST): richer summary for trend visibility.
$todayDow = (Get-Date).DayOfWeek
if ($todayDow -eq [System.DayOfWeek]::Monday) {
  $weeklyCmds = @(
    @("py", "scripts/check_scheduler_health.py", "--mode", "weekly", "--hours", "168", "--out-json", "prompts/scheduler-health-weekly.json", "--out-status", "prompts/scheduler-health-weekly.status.txt"),
    @("python", "scripts/check_scheduler_health.py", "--mode", "weekly", "--hours", "168", "--out-json", "prompts/scheduler-health-weekly.json", "--out-status", "prompts/scheduler-health-weekly.status.txt"),
    @("python3", "scripts/check_scheduler_health.py", "--mode", "weekly", "--hours", "168", "--out-json", "prompts/scheduler-health-weekly.json", "--out-status", "prompts/scheduler-health-weekly.status.txt")
  )
  foreach ($c in $weeklyCmds) {
    $exe = $c[0]
    $args = $c[1..($c.Length-1)]
    try {
      & $exe @args *> $null
      if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq 2) {
        Write-AlertHealthLog "OK" ("scheduler-health weekly ran via {0} exit={1}" -f $exe, $LASTEXITCODE)
        break
      } else {
        Write-AlertHealthLog "WARN" ("scheduler-health weekly failed via {0} exit={1}" -f $exe, $LASTEXITCODE)
      }
    } catch {
      Write-AlertHealthLog "WARN" ("scheduler-health weekly exception via {0}: {1}" -f $exe, $_.Exception.Message)
    }
  }
}

# Weekly needs freshness report (run on Wednesday JST): notify only latest fetched date.
if ($todayDow -eq [System.DayOfWeek]::Wednesday) {
  $needsCmds = @(
    @("py", "scripts/check_needs_freshness.py", "--out-status", "prompts/needs-freshness.status.txt"),
    @("python", "scripts/check_needs_freshness.py", "--out-status", "prompts/needs-freshness.status.txt"),
    @("python3", "scripts/check_needs_freshness.py", "--out-status", "prompts/needs-freshness.status.txt")
  )
  foreach ($c in $needsCmds) {
    $exe = $c[0]
    $args = $c[1..($c.Length-1)]
    try {
      & $exe @args *> $null
      if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq 1) {
        Write-AlertHealthLog "OK" ("needs-freshness weekly ran via {0} exit={1}" -f $exe, $LASTEXITCODE)
        break
      } else {
        Write-AlertHealthLog "WARN" ("needs-freshness weekly failed via {0} exit={1}" -f $exe, $LASTEXITCODE)
      }
    } catch {
      Write-AlertHealthLog "WARN" ("needs-freshness weekly exception via {0}: {1}" -f $exe, $_.Exception.Message)
    }
  }
}

# ingest ops logs into SQLite for analysis (best-effort, non-blocking)
$ingestCmds = @(
  @("py", "scripts/data/ingest_ops_logs.py"),
  @("python", "scripts/data/ingest_ops_logs.py"),
  @("python3", "scripts/data/ingest_ops_logs.py")
)

$ingestOk = $false
foreach ($c in $ingestCmds) {
  $exe = $c[0]
  $args = $c[1..($c.Length-1)]
  try {
    & $exe @args *> $null
    if ($LASTEXITCODE -eq 0) {
      Write-AlertHealthLog "OK" ("ops-log-ingest ran via {0}" -f $exe)
      $ingestOk = $true
      break
    } else {
      Write-AlertHealthLog "WARN" ("ops-log-ingest failed via {0} exit={1}" -f $exe, $LASTEXITCODE)
    }
  } catch {
    Write-AlertHealthLog "WARN" ("ops-log-ingest exception via {0}: {1}" -f $exe, $_.Exception.Message)
  }
}

if (-not $ingestOk) {
  Write-AlertHealthLog "WARN" "ops-log-ingest unavailable; continue without failing task"
}

exit 0
