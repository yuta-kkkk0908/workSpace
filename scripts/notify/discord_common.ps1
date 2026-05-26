$ErrorActionPreference = "Stop"

function Load-EnvFile([string]$envFilePath) {
  if (-not (Test-Path $envFilePath)) { return }
  Get-Content $envFilePath | ForEach-Object {
    if ($_ -match "^\s*#") { return }
    if ($_ -match "^\s*$") { return }
    if ($_ -notmatch "=") { return }
    $k, $v = $_.Split("=", 2)
    $v = $v.Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($k.Trim(), $v, "Process")
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

function Send-DiscordContent {
  param(
    [Parameter(Mandatory = $true)][string]$WebhookUrl,
    [Parameter(Mandatory = $true)][string]$Content,
    [Parameter(Mandatory = $true)][scriptblock]$WriteLog,
    [int]$MaxAttempts = 3
  )
  $body = @{ content = $Content } | ConvertTo-Json -Compress -Depth 3
  $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
  for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    try {
      Invoke-RestMethod -Method Post -Uri $WebhookUrl -ContentType "application/json; charset=utf-8" -Body $bodyBytes | Out-Null
      return $true
    } catch {
      $respBody = ""
      if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $respBody = $reader.ReadToEnd()
        $reader.Close()
      }
      & $WriteLog "ERROR" ("attempt={0}/{1} message={2} body={3}" -f $attempt, $MaxAttempts, $_.Exception.Message, $respBody)
      if ($attempt -lt $MaxAttempts) {
        Start-Sleep -Seconds (2 * $attempt)
        continue
      }
    }
  }
  return $false
}

function Send-DiscordPayload {
  param(
    [Parameter(Mandatory = $true)][string]$WebhookUrl,
    [Parameter(Mandatory = $true)][hashtable]$Payload,
    [Parameter(Mandatory = $true)][scriptblock]$WriteLog,
    [int]$MaxAttempts = 3
  )
  $body = $Payload | ConvertTo-Json -Compress -Depth 8
  $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($body)
  for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    try {
      Invoke-RestMethod -Method Post -Uri $WebhookUrl -ContentType "application/json; charset=utf-8" -Body $bodyBytes | Out-Null
      return $true
    } catch {
      $respBody = ""
      if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream()) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $respBody = $reader.ReadToEnd()
        $reader.Close()
      }
      & $WriteLog "ERROR" ("attempt={0}/{1} message={2} body={3}" -f $attempt, $MaxAttempts, $_.Exception.Message, $respBody)
      if ($attempt -lt $MaxAttempts) {
        Start-Sleep -Seconds (2 * $attempt)
        continue
      }
    }
  }
  return $false
}
