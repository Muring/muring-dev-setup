$ErrorActionPreference = 'Stop'
$installer = (Resolve-Path (Join-Path $PSScriptRoot '../../windows/install-orca-auto.ps1')).Path
$task = 'MuRing-Orca-Auto-Test-' + [guid]::NewGuid().ToString('N')
$root = Join-Path ([IO.Path]::GetTempPath()) $task
$directory = Join-Path $root 'installed space'
$app = Join-Path $root 'absent orca'
function Run($expected, $mode) {
  $arguments = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',$installer,'-TaskName',$task,'-Directory',$directory,'-AppDir',$app)
  if ($mode) { $arguments += $mode }
  & powershell.exe @arguments
  if ($LASTEXITCODE -ne $expected) { throw "Expected $expected for $mode, got $LASTEXITCODE" }
}
try {
  # Remove all external Node installations from PATH; use only the bundled runtime.
  $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot\System32\WindowsPowerShell\v1.0"
  Run 1 '-Check'
  Run 0 ''
  Run 0 '-Check'
  $deadline = (Get-Date).AddSeconds(30)
  $statePath = Join-Path $directory 'state/auto-status.json'
  while (-not (Test-Path $statePath) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
  if ((Get-Content $statePath -Raw | ConvertFrom-Json).status -ne 'not-installed') { throw 'Controller did not run using bundled runtime' }
  $firstPid = [int](Get-Content (Join-Path $directory 'state/controller.lock'))
  Run 0 ''
  Run 0 '-Check'
  if (Get-Process -Id $firstPid -ErrorAction SilentlyContinue) { throw 'Previous controller still running after reinstall' }
  Disable-ScheduledTask -TaskName $task | Out-Null
  Run 1 '-Check'
  Run 0 ''
  Add-Content (Join-Path $directory 'patch-engine.cjs') '// stale copy'
  Run 1 '-Check'
  Run 0 ''
  Run 0 '-Check'
  Remove-Item (Join-Path $directory 'patches/orca-1.4.215-wsl-rename.json')
  Run 1 '-Check'
  Run 0 ''
  Run 0 '-Check'
  Run 0 '-Remove'
  Run 1 '-Check'
  Write-Host 'PASS: no external Node, running scheduled task, reinstall stops owned controller, disabled/stale detection and repair, removal.'
} finally {
  Run 0 '-Remove'
  if (Test-Path $root) { Remove-Item $root -Recurse -Force }
}
