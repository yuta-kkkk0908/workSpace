$ErrorActionPreference = "Stop"

function Get-AiosPythonPath {
  param(
    [string]$Repo = "E:\workSpace"
  )

  $python312 = "C:\Users\yuta_\AppData\Local\Programs\Python\Python312\python.exe"
  if (Test-Path $python312) {
    return $python312
  }

  $venvPython = Join-Path $Repo ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    return $venvPython
  }

  $python = "C:\msys64\usr\bin\python.exe"
  if (Test-Path $python) {
    return $python
  }
  throw "python runtime not found"
}

function Invoke-HiddenPowerShellFile {
  param(
    [Parameter(Mandatory=$true)][string]$FilePath,
    [string[]]$Arguments = @()
  )

  $argList = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-WindowStyle", "Hidden",
    "-File", $FilePath
  ) + $Arguments

  $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argList -WindowStyle Hidden -Wait -PassThru
  return [int]$proc.ExitCode
}

function Get-AiosErrorCategory {
  param(
    [int]$ExitCode,
    [string]$Stage = ""
  )
  if ($ExitCode -eq 0) { return "ok" }
  $s = ($Stage | ForEach-Object { $_.ToLowerInvariant() })
  if ($s -match "discord|webhook|post_") { return "discord_delivery" }
  if ($s -match "collect_|fetch_|snapshot|source") { return "source_fetch" }
  if ($s -match "ingest_|db|sqlite") { return "db_error" }
  if ($s -match "auth|token|credential") { return "auth_error" }
  return "process_error"
}

function Write-AiosPipelineEvent {
  param(
    [string]$Repo = "E:\workSpace",
    [string]$Pipeline,
    [string]$Slot,
    [string]$Stage,
    [string]$Status,
    [int]$ReturnCode = 0,
    [string]$EventDate,
    [string]$Category = "",
    [string]$Detail = ""
  )
  $python = Get-AiosPythonPath -Repo $Repo
  $argList = @(
    "scripts/ops/log_pipeline_event.py",
    "--pipeline", $Pipeline,
    "--slot", $Slot,
    "--stage", $Stage,
    "--status", $Status,
    "--return-code", ([string]$ReturnCode),
    "--event-date", $EventDate,
    "--source-path", "scripts/ops/task_runner_common.ps1"
  )
  if (-not [string]::IsNullOrWhiteSpace($Category)) {
    $argList += @("--category", $Category)
  }
  if (-not [string]::IsNullOrWhiteSpace($Detail)) {
    $argList += @("--detail", $Detail)
  }
  & $python @argList | Out-Null
}
