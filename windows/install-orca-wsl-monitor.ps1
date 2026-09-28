# Opt-in per-user monitor, stored outside Orca's auto-update directory.
[CmdletBinding()]
param(
  [switch]$Remove,
  [switch]$Check,
  [string]$TaskName = 'MuRing-Orca-WSL-Patch-Monitor',
  [string]$Directory = (Join-Path $env:LOCALAPPDATA 'MuRingDevSetup\OrcaPatchMonitor')
)
$ErrorActionPreference = 'Stop'
$script = Join-Path $directory 'watch-orca-wsl-rename.ps1'
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -STA -WindowStyle Hidden -File "' + $script + '" -StateDir "' + $directory + '"'
$executable = Join-Path $PSHOME 'powershell.exe'
if ($Check) {
  try {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
    if (-not $task.Settings.Enabled -or $task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $executable -or $task.Actions[0].Arguments -ne $arguments) { exit 1 }
    if ($task.Principal.LogonType -ne 'Interactive' -or $task.Principal.RunLevel -ne 'Limited') { exit 1 }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $owner = $task.Principal.UserId
    if ($owner -notlike 'S-1-*') { $owner = (New-Object Security.Principal.NTAccount($owner)).Translate([Security.Principal.SecurityIdentifier]).Value }
    if ($owner -ne $identity.User.Value) { exit 1 }
    $logon = @($task.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' -and $_.Enabled })
    $repeat = @($task.Triggers | Where-Object { $_.Enabled -and $_.Repetition.Interval -eq 'PT5M' })
    if ($logon.Count -ne 1 -or $repeat.Count -ne 1) { exit 1 }
    $sources = @((Join-Path $PSScriptRoot 'watch-orca-wsl-rename.ps1')) + @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'patches') -Filter 'orca-*-wsl-rename.json' | ForEach-Object { $_.FullName })
    foreach ($source in $sources) {
      $destination = if ($source.EndsWith('.json')) { Join-Path (Join-Path $directory 'patches') ([IO.Path]::GetFileName($source)) } else { $script }
      if (-not (Test-Path -LiteralPath $destination) -or (Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $destination).Hash) { exit 1 }
    }
    Write-Host 'Orca patch monitor: task and installed files verified.'
    exit 0
  } catch { exit 1 }
}
if ($Remove) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host 'Orca patch monitor task removed. Diagnostic files retained.'
  exit 0
}
New-Item -ItemType Directory -Path (Join-Path $directory 'patches') -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'watch-orca-wsl-rename.ps1') -Destination $directory -Force
Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'patches') -Filter 'orca-*-wsl-rename.json' | Copy-Item -Destination (Join-Path $directory 'patches') -Force
$action = New-ScheduledTaskAction -Execute $executable -Argument $arguments
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$triggers = @(
  (New-ScheduledTaskTrigger -AtLogOn -User $user),
  (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(5) -RepetitionInterval (New-TimeSpan -Minutes 5))
)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Description 'Check Orca WSL rename patch after updates; notify only, never modify Orca.' -Force | Out-Null
Write-Host "Installed $taskName (logon and every 5 minutes). Status: $directory\status.json"
