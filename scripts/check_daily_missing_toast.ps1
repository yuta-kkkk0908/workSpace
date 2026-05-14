param(
    [string]$RepoPath = "E:\workSpace",
    [string]$Date = "today",
    [int]$Days = 7,
    [switch]$NotifyOk,
    [switch]$CopyPrompt
)

$ErrorActionPreference = "Continue"

$logPath = Join-Path $RepoPath "reminders.log"
$toastLogPath = Join-Path $RepoPath "reminders-toast.log"
$fallbackToastLogPath = Join-Path $env:TEMP "aios-reminders-toast.log"
$statusPath = Join-Path $RepoPath "prompts\pending-daily\latest.status.txt"
$promptPath = Join-Path $RepoPath "prompts\pending-daily\latest.prompt.md"
$clipboardPath = Join-Path $RepoPath "prompts\pending-daily\latest.clipboard.txt"

function Write-ReminderLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$timestamp $Message"
    try {
        $line | Out-File -FilePath $toastLogPath -Encoding utf8 -Append
    } catch {
        $line | Out-File -FilePath $fallbackToastLogPath -Encoding utf8 -Append
    }
}

Write-ReminderLog "start RepoPath=$RepoPath Date=$Date Days=$Days NotifyOk=$NotifyOk CopyPrompt=$CopyPrompt"
Write-ReminderLog "PSVersion=$($PSVersionTable.PSVersion) User=$env:USERNAME Session=$([System.Diagnostics.Process]::GetCurrentProcess().SessionId)"

try {
    Set-Location $RepoPath
    Write-ReminderLog "Set-Location ok: $(Get-Location)"
} catch {
    Write-ReminderLog "Set-Location failed: $($_.Exception.Message)"
    exit 2
}

if (-not (Test-Path "scripts\check_daily_missing.py")) {
    Write-ReminderLog "missing script at $(Join-Path (Get-Location) 'scripts\check_daily_missing.py')"
    exit 2
}

$output = & python "scripts\check_daily_missing.py" --date $Date --days $Days 2>&1
$exitCode = $LASTEXITCODE
$output | Out-File -FilePath $logPath -Encoding utf8
Write-ReminderLog "pythonExitCode=$exitCode"

if (Test-Path $statusPath) {
    $statusText = Get-Content $statusPath -Raw -Encoding UTF8
    Write-ReminderLog "statusPath exists"
} else {
    $statusText = "AIOS daily check finished, but status file was not found. See reminders.log."
    Write-ReminderLog "statusPath missing: $statusPath"
}

if ($exitCode -eq 0 -and -not $NotifyOk) {
    Write-ReminderLog "exit: no missing and NotifyOk=false"
    exit 0
}

if ($exitCode -ne 0 -and $CopyPrompt -and (Test-Path $clipboardPath)) {
    try {
        $clipboardText = Get-Content $clipboardPath -Raw -Encoding UTF8
        $copied = $false
        $copyError = $null

        try {
            Set-Clipboard -Value $clipboardText -ErrorAction Stop
            $copied = $true
            Write-ReminderLog ("clipboard copied via Set-Clipboard length=" + $clipboardText.Length)
        }
        catch {
            $copyError = $_.Exception.Message
            Write-ReminderLog ("Set-Clipboard failed: " + $copyError)
        }

        if (-not $copied) {
            $clipboardText | clip.exe
            Write-ReminderLog ("clipboard copied via clip.exe length=" + $clipboardText.Length)
        }

        $statusText = $statusText.Trim() + "`n補完プロンプトをクリップボードにコピーしました。"
    }
    catch {
        Write-ReminderLog ("clipboard copy failed: " + $_.Exception.Message)
        $statusText = $statusText.Trim() + "`nクリップボードコピーに失敗しました。reminders-toast.log を確認してください。"
    }
} elseif ($exitCode -ne 0 -and $CopyPrompt) {
    Write-ReminderLog "clipboardPath missing: $clipboardPath"
}

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$notifyIcon = New-Object System.Windows.Forms.NotifyIcon
$notifyIcon.Icon = [System.Drawing.SystemIcons]::Information
$notifyIcon.Visible = $true

if ($exitCode -eq 0) {
    $title = "AIOS daily OK"
    $icon = [System.Windows.Forms.ToolTipIcon]::Info
} else {
    $title = "AIOS daily missing - paste prompt"
    $icon = [System.Windows.Forms.ToolTipIcon]::Warning
}

$body = $statusText.Trim()
if ($body.Length -gt 240) {
    $body = $body.Substring(0, 237) + "..."
}

$notifyIcon.ShowBalloonTip(10000, $title, $body, $icon)
Write-ReminderLog "toast shown title=$title"
Start-Sleep -Seconds 12
$notifyIcon.Dispose()

# If YourChronicle is running, bring it back to foreground.
try {
    Add-Type -AssemblyName Microsoft.VisualBasic
    $p = Get-Process -Name "YourChronicle" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($p) {
        [Microsoft.VisualBasic.Interaction]::AppActivate($p.Id) | Out-Null
        Write-ReminderLog "AppActivate: YourChronicle pid=$($p.Id)"
    } else {
        Write-ReminderLog "AppActivate: YourChronicle not running"
    }
}
catch {
    Write-ReminderLog ("AppActivate failed: " + $_.Exception.Message)
}

Write-ReminderLog "done"
