# Read-only archive monitor. Never patches, quits, or downgrades Orca.
[CmdletBinding()]
param(
  [string]$AppDir = (Join-Path $env:LOCALAPPDATA 'Programs\orca'),
  [string]$StateDir = (Join-Path $env:LOCALAPPDATA 'MuRingDevSetup\OrcaPatchMonitor'),
  [string]$ManifestDirectory,
  [switch]$Quiet
)
$ErrorActionPreference = 'Stop'
if (-not $ManifestDirectory) { $ManifestDirectory = Join-Path $PSScriptRoot 'patches' }
$stateFile = Join-Path $StateDir 'status.json'
try {
  New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
  $previous = $null
  if (Test-Path -LiteralPath $stateFile) {
    try { $previous = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json } catch { }
  }
  $archive = Join-Path $AppDir 'resources\app.asar'
  $hash = $null; $version = $null; $status = 'not-installed'
  if (Test-Path -LiteralPath $archive) {
    $before = Get-Item -LiteralPath $archive
    $stamp = "$($before.Length):$($before.LastWriteTimeUtc.Ticks)"
    $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
    $after = Get-Item -LiteralPath $archive
    if ($stamp -ne "$($after.Length):$($after.LastWriteTimeUtc.Ticks)") { throw 'Orca is updating; retry at the next check.' }
    $status = 'unverified'
    foreach ($file in Get-ChildItem -LiteralPath $ManifestDirectory -Filter 'orca-*-wsl-rename.json') {
      $manifest = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
      if ($hash -eq $manifest.patchedSha256) { $status = 'patched'; $version = $manifest.version; break }
      if ($hash -eq $manifest.originalSha256) { $status = 'patch-missing'; $version = $manifest.version; break }
    }
  }
  $alert = $status -eq 'patch-missing' -or $status -eq 'unverified'
  $lastNotified = if ($alert) { $previous.lastNotifiedHash } else { $null }
  if ($alert -and -not $Quiet -and $lastNotified -ne $hash) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $icon = New-Object System.Windows.Forms.NotifyIcon
    try {
      $icon.Icon = [System.Drawing.SystemIcons]::Warning
      $icon.Visible = $true
      $message = if ($status -eq 'patch-missing') {
        "Orca $version WSL 이름 생성 패치가 없습니다. 자동 이름 변경이 실패할 수 있습니다. MuRing Dev Setup 패치를 다시 적용하세요."
      } else {
        'Orca 설치 파일이 변경되었습니다. WSL 이름 생성 수정이 유지되는지 검증이 필요합니다. 새 버전을 확인한 후 패치를 적용하세요.'
      }
      $icon.ShowBalloonTip(10000, 'Orca WSL 패치 확인 필요', $message, [System.Windows.Forms.ToolTipIcon]::Warning)
      Start-Sleep -Seconds 12
      $lastNotified = $hash
    } finally { $icon.Dispose() }
  }
  $result = [ordered]@{ checkedAt=(Get-Date).ToString('o'); status=$status; version=$version; sha256=$hash; alertRequired=$alert; lastNotifiedHash=$lastNotified }
  $json = $result | ConvertTo-Json
  $temp = "$stateFile.$([guid]::NewGuid().ToString('N')).tmp"
  try {
    [IO.File]::WriteAllText($temp, $json, (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $temp -Destination $stateFile -Force
  } finally { if (Test-Path -LiteralPath $temp) { Remove-Item -LiteralPath $temp } }
  $json
} catch {
  Write-Error $_
  exit 1
}
