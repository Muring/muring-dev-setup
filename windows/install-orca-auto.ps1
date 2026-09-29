[CmdletBinding()]
param(
  [switch]$Check,
  [switch]$Remove,
  [string]$TaskName = 'MuRing-Orca-WSL-AutoPatch',
  [string]$Directory = (Join-Path $env:LOCALAPPDATA 'MuRingDevSetup\OrcaAutoPatch'),
  [string]$AppDir = (Join-Path $env:LOCALAPPDATA 'Programs\orca')
)
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'orca-auto'
$node = Join-Path $Directory 'runtime\node.exe'
$executable = Join-Path $Directory 'launcher.exe'
$files = @('auto-patch.cjs','controller.cjs','patch-engine.cjs','combined-patch.cjs','terminal-patch.cjs','rename-main-hashes.json','notify.ps1','launch.ps1','launcher.cs','runtime-manifest.json','runtime\node.exe','runtime\LICENSE')
$manifest = Get-Content (Join-Path $source 'runtime-manifest.json') -Raw | ConvertFrom-Json
function Verify-Runtime($root) {
  foreach ($entry in $manifest.files.PSObject.Properties) {
    $file = Join-Path (Join-Path $root 'runtime') $entry.Name
    if (-not (Test-Path -LiteralPath $file) -or (Get-FileHash -LiteralPath $file).Hash -ne $entry.Value.sha256) { throw "Bundled runtime missing or invalid: $file" }
  }
}
function Stop-Controller {
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
  if ($task) { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
  $lock = Join-Path $Directory 'state\controller.lock'
  $controller = $null
  $ownedProcess = $null
  $launchers = @(Get-Process -Name 'launcher' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $executable })
  if (Test-Path -LiteralPath $lock) {
    $controllerPid = 0
    if ([int]::TryParse((Get-Content -LiteralPath $lock -Raw).Trim(), [ref]$controllerPid) -and $controllerPid -gt 0) {
      $candidate = Get-CimInstance Win32_Process -Filter "ProcessId=$controllerPid" -ErrorAction SilentlyContinue
      $expectedScript = Join-Path $Directory 'auto-patch.cjs'
      if ($candidate -and $candidate.Name -eq 'node.exe' -and $candidate.CommandLine.Contains($expectedScript)) {
        $controller = $candidate
        $ownedProcess = Get-Process -Id $controllerPid -ErrorAction SilentlyContinue
      }
    }
  }
  if ($task) { Stop-ScheduledTask -TaskName $TaskName }
  if ($controller) {
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($controller.ProcessId)" -ErrorAction SilentlyContinue
    if ($current -and $current.CreationDate -eq $controller.CreationDate) { Stop-Process -Id $controller.ProcessId -ErrorAction Stop }
  }
  # Termination is asynchronous; wait until executable mappings are released before copying.
  foreach ($process in (@($ownedProcess) + $launchers)) {
    if ($process -and -not $process.WaitForExit(10000)) { throw 'Owned auto-patch process did not stop in time' }
  }
}
if ($Remove) {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { Disable-ScheduledTask -TaskName $TaskName | Out-Null }
  Stop-Controller
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host 'Auto-patch task removed. Backups, receipts and installed files retained.'
  exit 0
}
if ($Check) {
  try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if (-not $task.Settings.Enabled -or $task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $executable -or -not [string]::IsNullOrEmpty($task.Actions[0].Arguments)) { exit 1 }
    if ($task.Principal.LogonType -ne 'Interactive' -or $task.Principal.RunLevel -ne 'Limited' -or $task.Settings.ExecutionTimeLimit -ne 'PT0S') { exit 1 }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $owner = $task.Principal.UserId
    if ($owner -notlike 'S-1-*') { $owner = (New-Object Security.Principal.NTAccount($owner)).Translate([Security.Principal.SecurityIdentifier]).Value }
    if ($owner -ne $identity.User.Value) { exit 1 }
    if ($task.Triggers.Count -ne 1 -or -not $task.Triggers[0].Enabled -or $task.Triggers[0].CimClass.CimClassName -ne 'MSFT_TaskLogonTrigger' -or $task.Triggers[0].Repetition.Interval) { exit 1 }
    if (-not (Test-Path -LiteralPath $executable) -or (Get-FileHash -LiteralPath $executable).Hash -ne (Get-Content -LiteralPath (Join-Path $Directory 'launcher.sha256') -Raw).Trim()) { exit 1 }
    foreach ($name in $files) {
      $installed = Join-Path $Directory $name
      if (-not (Test-Path -LiteralPath $installed) -or (Get-FileHash -LiteralPath $installed).Hash -ne (Get-FileHash -LiteralPath (Join-Path $source $name)).Hash) { exit 1 }
    }
    foreach ($file in Get-ChildItem (Join-Path $PSScriptRoot 'patches') -Filter 'orca-*-wsl-rename.json') {
      if ((Get-FileHash -LiteralPath (Join-Path $Directory ('patches\' + $file.Name))).Hash -ne (Get-FileHash -LiteralPath $file.FullName).Hash) { exit 1 }
    }
    Verify-Runtime $Directory
    $config = Get-Content -LiteralPath (Join-Path $Directory 'runtime.json') -Raw | ConvertFrom-Json
    if ($config.node -ne $node -or $config.appDir -ne $AppDir) { exit 1 }
    Write-Host 'Auto-patch installation verified. Patch status is recorded separately in state/auto-status.json.'
    exit 0
  } catch { exit 1 }
}
Verify-Runtime $source
# Stop only this installation's controller before replacing its runtime. Never stop Orca.
Stop-Controller
foreach ($name in $files) {
  $target = Join-Path $Directory $name
  New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
  Copy-Item -LiteralPath (Join-Path $source $name) -Destination $target -Force
}
New-Item -ItemType Directory -Path (Join-Path $Directory 'patches') -Force | Out-Null
Get-ChildItem (Join-Path $PSScriptRoot 'patches') -Filter 'orca-*-wsl-rename.json' | Copy-Item -Destination (Join-Path $Directory 'patches') -Force
@{node=$node; appDir=$AppDir; installedAt=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Directory 'runtime.json') -Encoding UTF8
# Compile a GUI-subsystem launcher so no console is created before hiding it.
if (Test-Path -LiteralPath $executable) { Remove-Item -LiteralPath $executable -Force }
Add-Type -TypeDefinition (Get-Content -LiteralPath (Join-Path $Directory 'launcher.cs') -Raw) -OutputAssembly $executable -OutputType WindowsApplication
(Get-FileHash -LiteralPath $executable).Hash | Set-Content -LiteralPath (Join-Path $Directory 'launcher.sha256') -Encoding ASCII
$action = New-ScheduledTaskAction -Execute $executable
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$triggers = @(New-ScheduledTaskTrigger -AtLogOn -User $user)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'Verify and restore the Orca WSL rename patch after updates; never stop Orca.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Auto-patch installed with bundled Node. Status: $Directory\state\auto-status.json"
