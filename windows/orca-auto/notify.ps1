$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
try {
  $icon.Icon = [System.Drawing.SystemIcons]::Warning
  $icon.Visible = $true
  $icon.ShowBalloonTip(10000, 'Orca 자동 패치 검토 필요', '새 Orca의 코드 구조가 검증 조건과 다릅니다. 자동 수정을 중단했으니 로컬 패치를 검토해주세요. 기존 작업은 종료하지 않았습니다.', [System.Windows.Forms.ToolTipIcon]::Warning)
  Start-Sleep -Seconds 12
} finally { $icon.Dispose() }
