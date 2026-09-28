param([switch]$Patched)
$ErrorActionPreference = 'Stop'
try {
  $archive = Join-Path $env:LOCALAPPDATA 'Programs\orca\resources\app.asar'
  if (-not (Test-Path -LiteralPath $archive)) { exit 1 }
  $hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
  foreach ($file in Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'patches') -Filter 'orca-*-wsl-rename.json') {
    $manifest = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
    if ($hash -eq $manifest.patchedSha256) { exit 0 }
    if (-not $Patched -and $hash -eq $manifest.originalSha256) { exit 0 }
  }
  exit 1
} catch { exit 1 }
