param([Parameter(Mandatory=$true)][string]$RequestBase64)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding = [Console]::OutputEncoding
$request = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($RequestBase64)) | ConvertFrom-Json
Add-Type -AssemblyName System.Web.Extensions
Add-Type -Path (Join-Path $PSScriptRoot 'StorageNative.cs') -ReferencedAssemblies 'System.Web.Extensions','System.Core'
if ($request.mode -eq 'discover') {
    $targets = @()
    foreach ($p in @($env:TEMP, (Join-Path $env:LOCALAPPDATA 'Packages'), (Join-Path $env:LOCALAPPDATA 'Orca'), (Join-Path $env:USERPROFILE '.cache'))) {
        $targets += @{path=$p;platform='windows';kind='directory'}
    }
    $wsl = @()
    try {
        foreach ($key in Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' -ErrorAction Stop) {
            $item = Get-ItemProperty -LiteralPath $key.PSPath
            $base = [Environment]::ExpandEnvironmentVariables($item.BasePath) -replace '^\\\\\?\\',''
            $vhd = Join-Path $base 'ext4.vhdx'
            $targets += @{path=$vhd;platform='windows';kind='wsl_vhd'}
            $wsl += @{distribution=$item.DistributionName;path=$vhd}
        }
    } catch { $wsl += @{state='unknown';reason=$_.Exception.GetType().Name} }
    # Exact configured swap location plus bounded first-level Temp discovery.
    $config = Join-Path $env:USERPROFILE '.wslconfig'
    if (Test-Path -LiteralPath $config) {
        foreach ($line in Get-Content -LiteralPath $config) {
            if ($line -match '^\s*swapFile\s*=\s*(.+)\s*$') {
                $swap = [Environment]::ExpandEnvironmentVariables($Matches[1].Trim().Replace('\\','\'))
                $targets += @{path=$swap;platform='windows';kind='swap'}
            }
        }
    }
    foreach ($dir in [IO.Directory]::EnumerateDirectories($env:TEMP)) {
        try {
            if (([IO.File]::GetAttributes($dir) -band [IO.FileAttributes]::ReparsePoint) -ne 0) { continue }
            $swap = Join-Path $dir 'swap.vhdx'
            if ([IO.File]::Exists($swap)) { $targets += @{path=$swap;platform='windows';kind='swap'} }
        } catch {}
    }
    $volumes = @()
    foreach ($drive in [IO.DriveInfo]::GetDrives()) {
        if ($drive.DriveType -ne 'Fixed') { continue }
        try { $volumes += @{path=$drive.Name;state='complete';total_bytes=$drive.TotalSize;free_bytes=$drive.AvailableFreeSpace} }
        catch { $volumes += @{path=$drive.Name;state='unknown';free_bytes=$null} }
    }
    @{targets=$targets;volumes=$volumes;wsl=$wsl;temp=$env:TEMP} | ConvertTo-Json -Depth 8 -Compress
} else {
    $cleanup = $request.mode -ne 'scan'
    $execute = $request.mode -eq 'apply'
    if ($execute -and $request.confirmed -ne $true) { throw 'Exact-path approval required' }
    $result = [StorageNative]::Inspect($request.path, [int]$request.timeout, $request.result_path, $cleanup, $execute, $request.fingerprint, [long]$request.logical_bytes)
    $result | ConvertTo-Json -Depth 8 -Compress
}
