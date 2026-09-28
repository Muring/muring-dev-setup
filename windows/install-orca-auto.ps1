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
$script = Join-Path $Directory 'launch.ps1'
$executable = Join-Path $PSHOME 'powershell.exe'
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -WindowStyle Hidden -File "' + $script + '"'
$files = @('auto-patch.cjs','controller.cjs','patch-engine.cjs','notify.ps1','launch.ps1','runtime-manifest.json','runtime\node.exe','runtime\LICENSE')
$manifest = Get-Content (Join-Path $source 'runtime-manifest.json') -Raw | ConvertFrom-Json
function Verify-Runtime($root) {
  foreach ($entry in $manifest.files.PSObject.Properties) {
    $file = Join-Path (Join-Path $root 'runtime') $entry.Name
    if (-not (Test-Path -LiteralPath $file) -or (Get-FileHash -LiteralPath $file).Hash -ne $entry.Value.sha256) { throw "Bundled runtime missing or invalid: $file" }
  }
}
function Stop-Controller {
  $lock = Join-Path $Directory 'state\controller.lock'
  $controller = $null
  if (Test-Path -LiteralPath $lock) {
    $controllerPid = 0
    if ([int]::TryParse((Get-Content -LiteralPath $lock -Raw).Trim(), [ref]$controllerPid) -and $controllerPid -gt 0) {
      $candidate = Get-CimInstance Win32_Process -Filter "ProcessId=$controllerPid" -ErrorAction SilentlyContinue
      $expectedScript = Join-Path $Directory 'auto-patch.cjs'
      if ($candidate -and $candidate.Name -eq 'node.exe' -and $candidate.CommandLine.Contains($expectedScript)) { $controller = $candidate }
    }
  }
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) { Stop-ScheduledTask -TaskName $TaskName }
  if ($controller) {
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($controller.ProcessId)" -ErrorAction SilentlyContinue
    if ($current -and $current.CreationDate -eq $controller.CreationDate) { Stop-Process -Id $controller.ProcessId -ErrorAction Stop }
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
    if (-not $task.Settings.Enabled -or $task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $executable -or $task.Actions[0].Arguments -ne $arguments) { exit 1 }
    if ($task.Principal.LogonType -ne 'Interactive' -or $task.Principal.RunLevel -ne 'Limited' -or $task.Settings.ExecutionTimeLimit -ne 'PT0S') { exit 1 }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $owner = $task.Principal.UserId
    if ($owner -notlike 'S-1-*') { $owner = (New-Object Security.Principal.NTAccount($owner)).Translate([Security.Principal.SecurityIdentifier]).Value }
    if ($owner -ne $identity.User.Value) { exit 1 }
    if (@($task.Triggers | Where-Object { $_.Enabled -and $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' }).Count -ne 1 -or @($task.Triggers | Where-Object { $_.Enabled -and $_.Repetition.Interval -eq 'PT1M' }).Count -ne 1) { exit 1 }
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
$action = New-ScheduledTaskAction -Execute $executable -Argument $arguments
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$triggers = @((New-ScheduledTaskTrigger -AtLogOn -User $user), (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)))
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'Verify and restore the Orca WSL rename patch after updates; never stop Orca.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Auto-patch installed with bundled Node. Status: $Directory\state\auto-status.json"
