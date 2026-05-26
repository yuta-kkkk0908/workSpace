$ErrorActionPreference = "Stop"

function Get-AiosPythonPath {
  param(
    [string]$Repo = "E:\workSpace"
  )

  $python = "C:\msys64\usr\bin\python.exe"
  if (Test-Path $python) {
    return $python
  }
  $venvPython = Join-Path $Repo ".venv\Scripts\python.exe"
  if (Test-Path $venvPython) {
    return $venvPython
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
