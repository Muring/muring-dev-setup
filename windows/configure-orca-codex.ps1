param([switch]$Check)
$ErrorActionPreference = 'Stop'
try {
  $runtimeRoot = Join-Path $PSScriptRoot 'orca-auto'
  $manifest = Get-Content -LiteralPath (Join-Path $runtimeRoot 'runtime-manifest.json') -Raw | ConvertFrom-Json
  $node = Join-Path $runtimeRoot 'runtime\node.exe'
  if (-not (Test-Path -LiteralPath $node) -or
      (Get-FileHash -LiteralPath $node -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.files.'node.exe'.sha256) {
    throw 'Bundled Windows Node is missing or invalid. Run windows/prepare-orca-runtime.py when installing from source.'
  }
  $arguments = @('--no-warnings', (Join-Path $PSScriptRoot 'orca-codex-settings.cjs'))
  if ($Check) { $arguments += '--check' }
  & $node @arguments
  exit $LASTEXITCODE
} catch {
  Write-Host "Orca Codex setup incomplete: $($_.Exception.Message)"
  exit 20
}
