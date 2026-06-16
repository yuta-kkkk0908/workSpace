$ErrorActionPreference = "Stop"

function Load-EnvFile([string]$envFilePath) {
  if (-not (Test-Path $envFilePath)) { return }
  foreach ($line in Get-Content $envFilePath -Encoding UTF8) {
    if ($line -match "^\s*#") { continue }
    if ($line -match "^\s*$") { continue }
    if ($line -notmatch "=") { continue }
    $k, $v = $line.Split("=", 2)
    $v = $v.Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($k.Trim(), $v, "Process")
  }
  if ($envFilePath -like "*.env" -and $envFilePath -notlike "*.env.local") {
    $localPath = Join-Path (Split-Path $envFilePath -Parent) ".env.local"
    if (Test-Path $localPath) {
      Load-EnvFile $localPath
    }
  }
}

function Get-TextSha256([string]$text) {
  return [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash([Text.Encoding]::UTF8.GetBytes($text))).Replace("-", "").ToLower()
}

function Split-ForDiscord([string]$text, [int]$limit = 1800) {
  $lines = ($text -replace "`r`n", "`n") -split "`n"
  $chunks = @()
  $buf = ""
  foreach ($line in $lines) {
    $cand = if ($buf) { "$buf`n$line" } else { $line }
    if ($cand.Length -le $limit) { $buf = $cand; continue }
    if ($buf) { $chunks += $buf }
    if ($line.Length -le $limit) {
      $buf = $line
    } else {
      for ($i = 0; $i -lt $line.Length; $i += $limit) {
        $len = [Math]::Min($limit, $line.Length - $i)
        $chunks += $line.Substring($i, $len)
      }
      $buf = ""
    }
  }
  if ($buf) { $chunks += $buf }
  return $chunks
}

function Get-WebExceptionBody {
  param(
    [Parameter(Mandatory = $false)]$Exception
  )
  try {
    if ($null -eq $Exception) { return "" }
    $resp = $Exception.Response
    if ($null -eq $resp) { return "" }
    $stream = $resp.GetResponseStream()
    if ($null -eq $stream) { return "" }
    $reader = New-Object System.IO.StreamReader($stream, [Text.Encoding]::UTF8)
    try {
      return $reader.ReadToEnd()
    } finally {
      $reader.Dispose()
    }
  } catch {
    return ""
  }
}

function Invoke-DiscordWebhookJson {
  param(
    [Parameter(Mandatory = $true)][string]$WebhookUrl,
    [Parameter(Mandatory = $true)][string]$Body,
    [Parameter(Mandatory = $true)][scriptblock]$WriteLog,
    [int]$MaxAttempts = 3
  )
  $utf8Body = [Text.Encoding]::UTF8.GetBytes($Body)
  $iwrParams = @{
    Method = "Post"
    Uri = $WebhookUrl
    ContentType = "application/json; charset=utf-8"
    Body = $utf8Body
    TimeoutSec = 20
    ErrorAction = "Stop"
  }
  try {
    if ((Get-Command Invoke-WebRequest).Parameters.ContainsKey("UseBasicParsing")) {
      $iwrParams["UseBasicParsing"] = $true
    }
  } catch {
    # Ignore parameter introspection failures and fall back to default behavior.
  }
  for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    try {
      $null = Invoke-WebRequest @iwrParams
      return $true
    } catch {
      $respBody = Get-WebExceptionBody $_.Exception
      & $WriteLog "ERROR" ("attempt={0}/{1} message={2} body={3}" -f $attempt, $MaxAttempts, $_.Exception.Message, $respBody)
      if ($attempt -lt $MaxAttempts) {
        Start-Sleep -Seconds (2 * $attempt)
        continue
      }
    }
  }
  return $false
}

function Send-DiscordContent {
  param(
    [Parameter(Mandatory = $true)][string]$WebhookUrl,
    [Parameter(Mandatory = $true)][string]$Content,
    [Parameter(Mandatory = $true)][scriptblock]$WriteLog,
    [int]$MaxAttempts = 3
  )
  $body = @{ content = $Content } | ConvertTo-Json -Compress -Depth 3
  return Invoke-DiscordWebhookJson -WebhookUrl $WebhookUrl -Body $body -WriteLog $WriteLog -MaxAttempts $MaxAttempts
}

function Send-DiscordPayload {
  param(
    [Parameter(Mandatory = $true)][string]$WebhookUrl,
    [Parameter(Mandatory = $true)][hashtable]$Payload,
    [Parameter(Mandatory = $true)][scriptblock]$WriteLog,
    [int]$MaxAttempts = 3
  )
  $body = $Payload | ConvertTo-Json -Compress -Depth 8
  return Invoke-DiscordWebhookJson -WebhookUrl $WebhookUrl -Body $body -WriteLog $WriteLog -MaxAttempts $MaxAttempts
}
