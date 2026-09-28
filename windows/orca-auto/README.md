# Orca 자동 재패치

설치 화면의 **Orca 자동 재패치**를 선택한다. 기본 선택은 해제되어 있다. EXE에 포함된 엔진, 검증 데이터, 전용 Windows Node 런타임을 현재 사용자의 `%LOCALAPPDATA%\MuRingDevSetup\OrcaAutoPatch`에 복사한다. Git clone이나 별도 Windows Node 설치는 필요 없다. 소스에서 직접 실행할 때만 `python3 windows/prepare-orca-runtime.py`로 빌드용 런타임을 준비한다.

현재 사용자의 `MuRing-Orca-WSL-AutoPatch` 예약 작업이 로그인 및 매 1분에 실행을 확인한다. 중복 실행을 막으며 상주 컨트롤러는 5초마다 변경을 검사한다. 공식 Orca 자동 업데이트는 유지한다. 기본 대상은 `%LOCALAPPDATA%\Programs\orca`이다.

## 적용 조건

- 알려진 원본 해시 또는 정확한 취약 함수 형태 하나에만 적용한다.
- WSL 실행 대상 전달, Windows/SSH 보존, JS 구문, ASAR 전체·블록 해시를 검사한다.
- Electron 내장 ASAR 검증이 활성화되었거나 불명확하면 변경하지 않는다.
- 원본 백업 후 같은 폴더에서 교체한다. 준비 중 원본이 바뀌면 재검사한다.
- 실행 중 파일이 잠기면 정상 종료 후 접근 가능한 시점까지 기다린다. Orca는 종료하거나 재시작하지 않는다. 변경된 코드는 다음 실행부터 반영된다.
- 미지원 구조는 원본을 보존하고 알림을 요청한다. 모든 미래 버전의 자동 수정을 보장하지 않는다. 패치 엔진 자체를 인터넷에서 자동 업데이트하지 않는다.

완료 표시는 자동화 설치 완료이며 현재 패치 완료와 별개다. `state/auto-status.json`에서 `patched`, `waiting-for-file-access`, `needs-review`, `not-installed` 상태를 확인한다. Windows 설정에 따라 알림이 표시되지 않을 수 있다. 백업은 `state/backups`, 적용 영수증은 `state/receipts`에 보관하며 자동 삭제하지 않는다.

기존 알림 전용 감시와 함께 선택하면 알림이 중복될 수 있다. 자동 복구 목적이면 자동 재패치를 선택하면 된다. 선택 해제만으로 기존 작업이 제거되지는 않는다.

## 관리 (PowerShell)

```powershell
# 설치 및 사용자 지정 Orca 경로 (스크립트가 있는 windows 폴더에서)
.\install-orca-auto.ps1 -AppDir 'D:\Apps\orca'
.\install-orca-auto.ps1 -Check -AppDir 'D:\Apps\orca'
# 자동화 제거: 자신이 설치한 컨트롤러만 종료하며 Orca와 백업은 유지
.\install-orca-auto.ps1 -Remove
```

스크립트가 없는 경우 작업 스케줄러에서 `MuRing-Orca-WSL-AutoPatch`를 사용 안 함으로 바꾼 후 실행 중인 해당 작업을 끝낸다. 자동화가 만든 영수증이 있는 버전은 컨트롤러 중지 및 Orca 정상 종료 후 아래처럼 복원한다.

```powershell
$root = Join-Path $env:LOCALAPPDATA 'MuRingDevSetup\OrcaAutoPatch'
& (Join-Path $root 'runtime\node.exe') (Join-Path $root 'auto-patch.cjs') --restore --once
```

복원 뒤 자동화를 다시 켜면 재패치되므로 중지 상태를 유지한다. 이전 수동 패치에는 자동화 영수증이 없으므로 기존 버전별 복원 스크립트를 사용한다. 재설치는 기존 백업과 영수증을 유지한다.

## 검증

`node --test tests/orca-auto/test.cjs`, Windows에서 `tests/orca-auto/windows-test.ps1` 및 `tests/orca-auto/install.ps1`을 실행한다. 설치 검사는 격리된 작업·폴더와 미설치 앱 경로를 사용하며 외부 Node가 PATH에 없는 조건에서 상주 실행을 확인한다. 사용자 Orca는 변경하지 않는다.
