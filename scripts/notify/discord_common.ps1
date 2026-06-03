$ErrorActionPreference = "Stop"

function Load-EnvFile([string]$envFilePath) {
  if (-not (Test-Path $envFilePath)) { return }
  Get-Content $envFilePath -Encoding UTF8 | ForEach-Object {
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
  for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    $client = $null
    $httpContent = $null
    try {
      $client = [System.Net.Http.HttpClient]::new()
      $client.Timeout = [TimeSpan]::FromSeconds(20)
      $httpContent = [System.Net.Http.StringContent]::new($body, [System.Text.Encoding]::UTF8, "application/json")
      $response = $client.PostAsync($WebhookUrl, $httpContent).GetAwaiter().GetResult()
      $response.EnsureSuccessStatusCode() | Out-Null
      return $true
    } catch {
      $respBody = ""
      if ($_.Exception.Response) {
        try {
          $respBody = $_.Exception.Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        } catch {
          $respBody = ""
        }
      }
      & $WriteLog "ERROR" ("attempt={0}/{1} message={2} body={3}" -f $attempt, $MaxAttempts, $_.Exception.Message, $respBody)
      if ($attempt -lt $MaxAttempts) {
        Start-Sleep -Seconds (2 * $attempt)
        continue
      }
    } finally {
      if ($httpContent) { $httpContent.Dispose() }
      if ($client) { $client.Dispose() }
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
  for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    $client = $null
    $httpContent = $null
    try {
      $client = [System.Net.Http.HttpClient]::new()
      $client.Timeout = [TimeSpan]::FromSeconds(20)
      $httpContent = [System.Net.Http.StringContent]::new($body, [System.Text.Encoding]::UTF8, "application/json")
      $response = $client.PostAsync($WebhookUrl, $httpContent).GetAwaiter().GetResult()
      $response.EnsureSuccessStatusCode() | Out-Null
      return $true
    } catch {
      $respBody = ""
      if ($_.Exception.Response) {
        try {
          $respBody = $_.Exception.Response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        } catch {
          $respBody = ""
        }
      }
      & $WriteLog "ERROR" ("attempt={0}/{1} message={2} body={3}" -f $attempt, $MaxAttempts, $_.Exception.Message, $respBody)
      if ($attempt -lt $MaxAttempts) {
        Start-Sleep -Seconds (2 * $attempt)
        continue
      }
    } finally {
      if ($httpContent) { $httpContent.Dispose() }
      if ($client) { $client.Dispose() }
    }
  }
  return $false
}
