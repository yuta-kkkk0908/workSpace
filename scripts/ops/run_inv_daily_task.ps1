Set-Location 'E:\workSpace'
New-Item -ItemType Directory -Force -Path 'E:\workSpace\logs' | Out-Null
$d = Get-Date -Format 'yyyy-MM-dd'

& 'C:\Users\yuta_\AppData\Local\Programs\Python\Python312\python.exe' `
  'E:\workSpace\scripts\pipelines\daily.py' `
  --date $d `
  --seed-list rough_backtest_light `
  --min-count 8 `
  >> 'E:\workSpace\logs\inv-daily-task.log' 2>&1

$rc = $LASTEXITCODE

# If YourChronicle is running, bring it back to foreground.
try {
  Add-Type -AssemblyName Microsoft.VisualBasic
  $p = Get-Process -Name "YourChronicle" -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($p) {
    [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) | Out-Null
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] AppActivate: YourChronicle pid=$($p.Id)" | Out-File -FilePath 'E:\workSpace\logs\inv-daily-task.log' -Encoding utf8 -Append
  } else {
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] AppActivate: YourChronicle not running" | Out-File -FilePath 'E:\workSpace\logs\inv-daily-task.log' -Encoding utf8 -Append
  }
}
catch {
  "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] AppActivate failed: $($_.Exception.Message)" | Out-File -FilePath 'E:\workSpace\logs\inv-daily-task.log' -Encoding utf8 -Append
}

exit $rc
