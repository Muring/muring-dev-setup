# Integration test using a supplied, verified original archive. Never targets the installed app.
param([Parameter(Mandatory=$true)][string]$OriginalArchive, [string]$Version = '1.4.202')
$ErrorActionPreference = 'Stop'
$fix = Join-Path $PSScriptRoot '..\windows\fix-orca-wsl-rename.ps1'
$manifest = Get-Content (Join-Path $PSScriptRoot "..\windows\patches\orca-$Version-wsl-rename.json") -Raw | ConvertFrom-Json
$root = Join-Path ([System.IO.Path]::GetTempPath()) ('orca-bootstrap-test-' + [guid]::NewGuid())
$target = Join-Path $root 'resources\app.asar'
function Assert($condition, $message) { if (-not $condition) { throw $message } }
function Hash($path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Run-Fix($expected, [switch]$Restore) {
  $arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $fix, '-AppDir', $root)
  if ($Restore) { $arguments += '-Restore' }
  & powershell.exe @arguments
  Assert ($LASTEXITCODE -eq $expected) "Unexpected exit code $LASTEXITCODE (wanted $expected)"
}
function Check-Monitor($expected) {
  $monitor = Join-Path $PSScriptRoot '..\windows\watch-orca-wsl-rename.ps1'
  $json = & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $monitor -AppDir $root -StateDir (Join-Path $root 'monitor') -Quiet
  Assert ($LASTEXITCODE -eq 0) 'Monitor failed.'
  $result = $json | ConvertFrom-Json
  Assert ($result.status -eq $expected) "Monitor: expected $expected, got $($result.status)"
  Assert (-not $result.lastNotifiedHash) 'Quiet check consumed a notification.'
}
try {
  Assert ((Hash $OriginalArchive) -eq $manifest.originalSha256) 'Supply the verified original archive.'
  New-Item -ItemType Directory -Path (Join-Path $root 'resources') | Out-Null
  Run-Fix 1 # Missing installation.
  Check-Monitor 'not-installed'
  [System.IO.File]::WriteAllText($target, 'unknown version')
  Check-Monitor 'unverified'
  $unknownHash = Hash $target
  Run-Fix 1
  Assert ((Hash $target) -eq $unknownHash) 'Unknown archive was modified.'
  Copy-Item -LiteralPath $OriginalArchive -Destination $target -Force
  Check-Monitor 'patch-missing'
  $lock = [System.IO.File]::Open($target, 'Open', 'Read', 'Read')
  try { Run-Fix 1 } finally { $lock.Dispose() }
  Assert ((Hash $target) -eq $manifest.originalSha256) 'Locked archive was modified.'
  Run-Fix 0
  Assert ((Hash $target) -eq $manifest.patchedSha256) 'Patch differs from verified archive.'
  Assert ((Hash "$target.bootstrap-wsl-rename.$Version.original") -eq $manifest.originalSha256) 'Invalid backup.'
  Check-Monitor 'patched'
  Run-Fix 0 # Idempotence.
  Run-Fix 0 -Restore
  Assert ((Hash $target) -eq $manifest.originalSha256) 'Restore failed.'
  Run-Fix 0 -Restore
  Check-Monitor 'patch-missing'
  [System.IO.File]::WriteAllText("$target.bootstrap-wsl-rename.$Version.original", 'corrupt')
  Run-Fix 1
  Assert ((Hash $target) -eq $manifest.originalSha256) 'Bad backup altered installation.'
  Assert (@(Get-ChildItem (Join-Path $root 'resources') -Filter '*.tmp').Count -eq 0) 'Temporary file leaked.'
  Write-Host 'PASS: missing/unknown/locked archive, apply, backup, repeat, restore, corrupt backup, cleanup.'
} finally { if (Test-Path $root) { Remove-Item -LiteralPath $root -Recurse -Force } }
