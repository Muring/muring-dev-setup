$ErrorActionPreference = 'Stop'
$config = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'runtime.json') -Raw | ConvertFrom-Json
$log = Join-Path $PSScriptRoot 'controller.log'
if ((Test-Path -LiteralPath $log) -and (Get-Item -LiteralPath $log).Length -gt 262144) { Move-Item -LiteralPath $log -Destination "$log.previous" -Force }
& $config.node (Join-Path $PSScriptRoot 'auto-patch.cjs') --app-dir $config.appDir >> $log 2>&1
exit $LASTEXITCODE
