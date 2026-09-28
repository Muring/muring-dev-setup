# Real scheduled-task integration, isolated from the user's monitor task/files.
$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot '..\windows\install-orca-wsl-monitor.ps1'
$taskName = 'MuRing-Orca-Monitor-Test-' + [guid]::NewGuid().ToString('N')
$directory = Join-Path ([IO.Path]::GetTempPath()) $taskName
function Run($expected, $mode) {
  $args = @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', $installer, '-TaskName', $taskName, '-Directory', $directory)
  if ($mode) { $args += $mode }
  & powershell.exe @args
  if ($LASTEXITCODE -ne $expected) { throw "Expected $expected for $mode, got $LASTEXITCODE" }
}
try {
  Run 1 '-Check'
  Run 0 ''
  Run 0 '-Check'
  Run 0 ''
  Run 0 '-Check'
  Disable-ScheduledTask -TaskName $taskName | Out-Null
  Run 1 '-Check'
  Enable-ScheduledTask -TaskName $taskName | Out-Null
  $script = Join-Path $directory 'watch-orca-wsl-rename.ps1'
  Add-Content -LiteralPath $script -Value '# stale copy'
  Run 1 '-Check'
  Run 0 ''
  Run 0 '-Check'
  Remove-Item -LiteralPath (Join-Path $directory 'patches\orca-1.4.215-wsl-rename.json')
  Run 1 '-Check'
  Run 0 ''
  Run 0 '-Check'
  Run 0 '-Remove'
  Run 1 '-Check'
  Write-Host 'PASS: isolated task install, repeat, disabled detection, script/manifest repair, removal.'
} finally {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  if (Test-Path -LiteralPath $directory) { Remove-Item -LiteralPath $directory -Recurse -Force }
}
