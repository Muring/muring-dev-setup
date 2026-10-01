$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$scriptRoot = Join-Path $PSScriptRoot '..\skills\storage-maintenance\scripts'
Add-Type -AssemblyName System.Web.Extensions
Add-Type -Path (Join-Path $scriptRoot 'StorageNative.cs') -ReferencedAssemblies 'System.Web.Extensions','System.Core'
$root = Join-Path $env:TEMP ('storage-maintenance-fixture-' + [guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($root) | Out-Null
function Assert($Condition, $Message) { if (-not $Condition) { throw $Message } }
try {
    $candidate = Join-Path $root 'candidate'
    [IO.Directory]::CreateDirectory($candidate) | Out-Null
    [IO.File]::WriteAllBytes((Join-Path $candidate 'data'), [byte[]](1,2,3,4,5))
    $scan = [StorageNative]::Inspect($candidate, 10, '', $false, $false, '', 0)
    Assert ($scan.state -eq 'complete' -and $scan.logical_bytes -eq 5) ('scan: ' + ($scan | ConvertTo-Json -Compress))
    Assert ($scan.allocated_bytes -ge 0) 'allocated bytes missing'
    $inspect = [StorageNative]::Inspect($candidate, 10, '', $true, $false, '', 0)
    Assert ([IO.File]::Exists((Join-Path $candidate 'data'))) 'read-only inspect deleted a file'
    $bad = [StorageNative]::Inspect($candidate, 10, '', $true, $true, 'incorrect', 5)
    Assert ($bad.state -eq 'refused_or_partial' -and [IO.File]::Exists((Join-Path $candidate 'data'))) 'stale approval was not refused'
    $inspect = [StorageNative]::Inspect($candidate, 10, '', $true, $false, '', 0)
    $result = [StorageNative]::Inspect($candidate, 10, '', $true, $true, $inspect.fingerprint, 5)
    Assert ($result.state -eq 'deleted' -and -not [IO.Directory]::Exists($candidate)) ('fixture deletion: ' + ($result | ConvertTo-Json -Compress))
    $missing = [StorageNative]::Inspect((Join-Path $root 'missing'), 10, '', $false, $false, '', 0)
    Assert ($missing.state -eq 'unknown' -and $null -eq $missing.logical_bytes) 'missing path became zero'
    $timeout = [StorageNative]::Inspect($root, 0, '', $false, $false, '', 0)
    Assert ($timeout.state -eq 'partial' -and $null -eq $timeout.logical_bytes) 'timeout became complete or zero'
    $aclPath = Join-Path $root 'acl-denied'; [IO.Directory]::CreateDirectory($aclPath) | Out-Null
    [IO.File]::WriteAllText((Join-Path $aclPath 'secret'),'fixture')
    $savedAcl = Get-Acl -LiteralPath $aclPath
    try {
        $changedAcl = Get-Acl -LiteralPath $aclPath
        $who = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $rule = New-Object Security.AccessControl.FileSystemAccessRule($who,'ReadAndExecute','ContainerInherit,ObjectInherit','None','Deny')
        $changedAcl.AddAccessRule($rule)
        Set-Acl -LiteralPath $aclPath -AclObject $changedAcl
        $deniedAcl = [StorageNative]::Inspect($aclPath,10,'',$false,$false,'',0)
        Assert ($deniedAcl.state -ne 'complete' -and $null -eq $deniedAcl.logical_bytes) 'ACL failure became complete or zero'
    } finally { Set-Acl -LiteralPath $aclPath -AclObject $savedAcl }
    $protected = Join-Path $root '.claude'
    [IO.Directory]::CreateDirectory($protected) | Out-Null
    $denied = [StorageNative]::Inspect($protected, 10, '', $true, $false, '', 0)
    Assert ($denied.state -eq 'unknown') 'protected directory not refused'
    $links = Join-Path $root 'hardlinks'; [IO.Directory]::CreateDirectory($links) | Out-Null
    $one = Join-Path $links 'one'; $two = Join-Path $links 'two'
    [IO.File]::WriteAllBytes($one,[byte[]](1,2,3,4,5))
    New-Item -ItemType HardLink -Path $two -Target $one | Out-Null
    $count = [StorageNative]::Inspect($links, 10, '', $false, $false, '', 0)
    Assert ($count.logical_bytes -eq 5 -and $count.duplicate_links -eq 1) 'hardlink counted twice'
    $refused = [StorageNative]::Inspect($links, 10, '', $true, $true, $count.fingerprint, 5)
    Assert ($refused.state -eq 'refused_or_partial') 'hardlink cleanup not refused'
    $outside = Join-Path $root 'outside'; [IO.Directory]::CreateDirectory($outside) | Out-Null
    [IO.File]::WriteAllText((Join-Path $outside 'keep'),'keep')
    $junction = Join-Path $root 'junction'; New-Item -ItemType Junction -Path $junction -Target $outside | Out-Null
    $escape = [StorageNative]::Inspect($junction,10,'',$true,$false,'',0)
    Assert ($escape.state -eq 'unknown' -and [IO.File]::Exists((Join-Path $outside 'keep'))) 'junction escape not refused'
    [IO.Directory]::Delete($junction)
    Write-Output 'PASS: native metadata, allocation, read-only, stale approval refusal, fixture deletion, timeout, ACL failure, unknown path, protected data, hardlink dedup/refusal, junction refusal'
} finally {
    # Only fixtures created in this process; no user cleanup candidates.
    if ([IO.Directory]::Exists($root)) { [IO.Directory]::Delete($root,$true) }
}
