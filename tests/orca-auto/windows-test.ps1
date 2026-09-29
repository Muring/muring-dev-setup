$ErrorActionPreference = 'Stop'
$node = (Resolve-Path (Join-Path $PSScriptRoot '../../windows/orca-auto/runtime/node.exe')).ProviderPath
$root = Join-Path ([IO.Path]::GetTempPath()) ('muring-auto-test-' + [guid]::NewGuid())
$app = Join-Path $root 'app space'
$state = Join-Path $root 'state'
$target = Join-Path $app 'resources\app.asar'
$process = $null; $lock = $null
function Read-State { Get-Content -LiteralPath (Join-Path $state 'auto-status.json') -Raw -ErrorAction SilentlyContinue | ConvertFrom-Json }
function Wait-State($expected) {
  $deadline = (Get-Date).AddSeconds(45)
  do {
    $value = Read-State
    if ($value.status -eq $expected) { return $value }
    Start-Sleep -Seconds 1
  } while ((Get-Date) -lt $deadline)
  throw "Expected $expected; got $($value | ConvertTo-Json -Compress)"
}
try {
  New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
  & $node (Join-Path $PSScriptRoot 'make-fixtures.cjs') $root
  if ($LASTEXITCODE -ne 0) { throw 'Fixture generation failed' }
  Copy-Item -LiteralPath (Join-Path $root 'first.asar') -Destination $target
  $lock = [IO.File]::Open($target, 'Open', 'Read', 'Read')
  $arguments = '"' + (Join-Path $PSScriptRoot '../../windows/orca-auto/auto-patch.cjs') + '" --app-dir "' + $app + '" --state-dir "' + $state + '" --quiet'
  $process = Start-Process -FilePath $node -ArgumentList $arguments -WindowStyle Hidden -PassThru
  Wait-State 'waiting-for-file-access' | Out-Null
  if ((Get-FileHash $target).Hash -ne (Get-FileHash (Join-Path $root 'first.asar')).Hash) { throw 'Locked file changed' }
  $lock.Dispose(); $lock = $null
  $first = Wait-State 'patched'
  if ($first.version -ne '1.4.999') { throw 'Wrong first version' }
  Copy-Item -LiteralPath (Join-Path $root 'next.asar') -Destination $target -Force
  $deadline = (Get-Date).AddSeconds(45)
  do { Start-Sleep -Seconds 1; $next=Read-State } while (($next.status -ne 'patched' -or $next.version -ne '1.4.1000') -and (Get-Date) -lt $deadline)
  if ($next.version -ne '1.4.1000' -or $next.status -ne 'patched') { throw 'Next update did not repair itself' }
  if (@(Get-ChildItem (Join-Path $state 'backups') -Filter '*.asar').Count -ne 2) { throw 'Missing backups' }
  Stop-Process -Id $process.Id; $process.WaitForExit(); $process=$null
  & $node (Join-Path $PSScriptRoot '../../windows/orca-auto/auto-patch.cjs') --app-dir $app --state-dir $state --restore --quiet
  if ($LASTEXITCODE -ne 0 -or (Get-FileHash $target).Hash -ne (Get-FileHash (Join-Path $root 'next.asar')).Hash) { throw 'Restore mismatch' }
  Copy-Item -LiteralPath (Join-Path $root 'unknown.asar') -Destination $target -Force
  Start-Sleep -Seconds 4
  & $node (Join-Path $PSScriptRoot '../../windows/orca-auto/auto-patch.cjs') --app-dir $app --state-dir $state --once --quiet
  if ((Read-State).status -ne 'needs-review' -or (Get-FileHash $target).Hash -ne (Get-FileHash (Join-Path $root 'unknown.asar')).Hash) { throw 'Unknown structure was changed' }
  Write-Host 'PASS: real Windows lock deferral, automatic retry after unlock, two unlisted versions, backups, restore, unsupported structure refusal.'
} finally {
  if ($lock) { $lock.Dispose() }
  if ($process -and -not $process.HasExited) { Stop-Process -Id $process.Id }
  if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
