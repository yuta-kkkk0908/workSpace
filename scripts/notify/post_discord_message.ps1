param(
  [string]$Repo = "E:\workSpace",
  [Parameter(Mandatory = $true)][string]$Kind,
  [Parameter(Mandatory = $true)][string]$MessagePath,
  [Parameter(Mandatory = $true)][string]$PrimaryWebhookEnv,
  [string]$FallbackWebhookEnv = "",
  [string]$HashFile = "",
  [string]$PendingPrefix = "",
  [switch]$SkipIfUnchanged,
  [switch]$AllowEmptyMessage,
  [switch]$SkipIfMessageMissing,
  [switch]$SkipIfMessageEmpty,
  [int]$SplitLimit = 1800,
  [switch]$AsEmbed,
  [switch]$NotifyOnUnchanged,
  [string]$UnchangedStreakFile = "",
  [int]$UnchangedFailThreshold = 0
)

$ErrorActionPreference = "Stop"

. (Join-Path $Repo "scripts\notify\discord_common.ps1")

$kindValue = if ($null -eq $Kind) { "" } else { [string]$Kind }
$kindUpper = $kindValue.ToUpperInvariant()
$kindLower = $kindValue.ToLowerInvariant()
$logDir = Join-Path $Repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("discord-{0}.log" -f $kindLower)

function Write-NotifyLog([string]$level, [string]$message) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  "[$ts] [$level] $message" | Out-File -FilePath $logFile -Encoding utf8 -Append
}

function Infer-UnchangedReason([string]$text) {
  $t = if ($null -eq $text) { "" } else { $text.ToLowerInvariant() }
  if ($t -match "候補なし|候補 なし|シグナルなし|signal.*none|no signal|0件|0 件|no candidate") {
    return "DATA_THIN"
  }
  return "RULE_THIN"
}

function Get-Streak([string]$path) {
  if (-not $path) { return 0 }
  if (-not (Test-Path $path)) { return 0 }
  try {
    $raw = (Get-Content $path -Raw -Encoding UTF8).Trim()
    if (-not $raw) { return 0 }
    return [int]$raw
  } catch {
    return 0
  }
}

function Set-Streak([string]$path, [int]$value) {
  if (-not $path) { return }
  $dir = Split-Path -Parent $path
  if ($dir) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
  Set-Content -Path $path -Value ([string]$value) -Encoding UTF8
}

function Get-AsOfLine([string]$path) {
  try {
    if (-not (Test-Path $path)) { return "" }
    $ts = (Get-Item -LiteralPath $path).LastWriteTime
    return "AsOf: {0} JST" -f $ts.ToString("yyyy-MM-dd HH:mm")
  } catch {
    return ""
  }
}

Load-EnvFile (Join-Path $Repo ".env")
$primaryUrl = [Environment]::GetEnvironmentVariable($PrimaryWebhookEnv, "Process")
if (-not $primaryUrl) { throw "$PrimaryWebhookEnv is empty" }
$fallbackUrl = $null
if ($FallbackWebhookEnv) {
  $fallbackUrl = [Environment]::GetEnvironmentVariable($FallbackWebhookEnv, "Process")
}

if (-not (Test-Path $MessagePath)) {
  if ($SkipIfMessageMissing) {
    Write-NotifyLog "SKIP" ("message file not found: {0}" -f $MessagePath)
    Write-Host ("[{0}] {1}: skipped (message file missing)" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $kindUpper)
    exit 0
  }
  throw "message file not found: $MessagePath"
}
$msg = [string](Get-Content $MessagePath -Raw -Encoding UTF8)
if ([string]::IsNullOrWhiteSpace($msg)) {
  if ($SkipIfMessageEmpty) {
    Write-NotifyLog "SKIP" "message is empty"
    Write-Host ("[{0}] {1}: skipped (empty message)" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $kindUpper)
    exit 0
  }
  if (-not $AllowEmptyMessage) { throw "message is empty" }
}

if ($SkipIfUnchanged -and $HashFile) {
  $hash = Get-TextSha256 $msg
  $last = if (Test-Path $HashFile) { (Get-Content $HashFile -Raw -Encoding UTF8).Trim() } else { "" }
  if ($hash -eq $last) {
    $reason = Infer-UnchangedReason $msg
    $streak = (Get-Streak $UnchangedStreakFile) + 1
    Set-Streak $UnchangedStreakFile $streak
    if ($NotifyOnUnchanged) {
      $unchangedText = "[{0}] unchanged reason={1} streak={2}" -f $kindUpper, $reason, $streak
      if ($AsEmbed) {
        $payload = @{
          embeds = @(
            @{
              title = "{0} Update" -f $kindUpper
              description = $unchangedText
              color = 9807270
            }
          )
        }
        $null = Send-DiscordPayload -WebhookUrl $primaryUrl -Payload $payload -WriteLog {
          param($level, $message)
          Write-NotifyLog $level ("unchanged notify {0}" -f $message)
        }
      } else {
        $null = Send-DiscordContent -WebhookUrl $primaryUrl -Content $unchangedText -WriteLog {
          param($level, $message)
          Write-NotifyLog $level ("unchanged notify {0}" -f $message)
        }
      }
    }
    Write-Host ("[{0}] {1}: skipped (unchanged message)" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $kindUpper)
    Write-NotifyLog "QUALITY_WARN" ("unchanged hash={0} reason={1} streak={2}" -f $hash, $reason, $streak)
    if ($UnchangedFailThreshold -gt 0 -and $streak -ge $UnchangedFailThreshold) {
      Write-NotifyLog "QUALITY_ERROR" ("unchanged threshold reached threshold={0} streak={1}" -f $UnchangedFailThreshold, $streak)
      exit 2
    }
    exit 0
  }
}

$asOfLine = Get-AsOfLine $MessagePath
$msgToSend = if ($asOfLine) { "$asOfLine`n$msg" } else { $msg }
$parts = @(Split-ForDiscord $msgToSend $SplitLimit)
Write-NotifyLog "START" ("parts={0} msg_len={1}" -f $parts.Count, $msg.Length)
$deliveryFailed = $false

for ($i = 0; $i -lt $parts.Count; $i++) {
  $content = if ($parts.Count -gt 1) { "[{0}/{1}]`n{2}" -f ($i + 1), $parts.Count, $parts[$i] } else { $parts[$i] }
  if ($AsEmbed) {
    $title = "{0} Update" -f $kindUpper
    if ($parts.Count -gt 1) { $title = "{0} ({1}/{2})" -f $title, ($i + 1), $parts.Count }
    $payload = @{
      embeds = @(
        @{
          title = $title
          description = $parts[$i]
          color = 3447003
        }
      )
    }
    $sent = Send-DiscordPayload -WebhookUrl $primaryUrl -Payload $payload -WriteLog {
      param($level, $message)
      Write-NotifyLog $level ("part={0}/{1} {2}" -f ($i + 1), $parts.Count, $message)
    }
  } else {
    $sent = Send-DiscordContent -WebhookUrl $primaryUrl -Content $content -WriteLog {
      param($level, $message)
      Write-NotifyLog $level ("part={0}/{1} {2}" -f ($i + 1), $parts.Count, $message)
    }
  }
  if ($sent) { continue }

  if ($fallbackUrl) {
    if ($AsEmbed) {
      $fallbackPayload = @{
        content = "[{0}-FALLBACK] primary webhook unreachable." -f $kindUpper
        embeds = @(
          @{
            title = "{0} Fallback" -f $kindUpper
            description = $parts[$i]
            color = 15158332
          }
        )
      }
      $fbSent = Send-DiscordPayload -WebhookUrl $fallbackUrl -Payload $fallbackPayload -WriteLog {
        param($level, $message)
        Write-NotifyLog $level ("fallback part={0}/{1} {2}" -f ($i + 1), $parts.Count, $message)
      }
    } else {
      $fallbackContent = "[{0}-FALLBACK] primary webhook unreachable.`n{1}" -f $kindUpper, $content
      $fbSent = Send-DiscordContent -WebhookUrl $fallbackUrl -Content $fallbackContent -WriteLog {
        param($level, $message)
        Write-NotifyLog $level ("fallback part={0}/{1} {2}" -f ($i + 1), $parts.Count, $message)
      }
    }
    if ($fbSent) {
      Write-NotifyLog "WARN" ("fallback_posted part={0}/{1}" -f ($i + 1), $parts.Count)
      continue
    }
  }

  $deliveryFailed = $true
  Write-NotifyLog "ERROR" ("failed_to_deliver part={0}/{1}" -f ($i + 1), $parts.Count)
}

if ($deliveryFailed) {
  $pendingDir = Join-Path $Repo "prompts\pending"
  New-Item -ItemType Directory -Force -Path $pendingDir | Out-Null
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $prefix = if ($PendingPrefix) { $PendingPrefix } else { $kindLower }
  $pendingFile = Join-Path $pendingDir ("{0}-discord-pending-{1}.txt" -f $prefix, $stamp)
  Set-Content -Path $pendingFile -Value $msg -Encoding UTF8
  Write-Host ("[{0}] {1}: queued pending file={2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $kindUpper, $pendingFile)
  Write-NotifyLog "WARN" ("queued pending={0}" -f $pendingFile)
  exit 0
}

if ($SkipIfUnchanged -and $HashFile) {
  Set-Content -Path $HashFile -Value (Get-TextSha256 $msg) -Encoding UTF8
  Set-Streak $UnchangedStreakFile 0
  Write-NotifyLog "OK" ("posted parts={0} hash={1}" -f $parts.Count, (Get-TextSha256 $msg))
} else {
  Write-NotifyLog "OK" ("posted parts={0}" -f $parts.Count)
}
Write-Host ("[{0}] {1}: posted parts={2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $kindUpper, $parts.Count)
exit 0
