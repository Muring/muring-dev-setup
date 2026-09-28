# Orca WSL 이름 생성 패치

지원 버전은 Windows Orca **1.4.202, 1.4.215**이다. `orca-<version>-wsl-rename.json`의 원본·수정본 SHA-256과 정확히 일치하는 설치 파일만 처리한다.

각 JSON은 원본 `app.asar` 기준 UTF-8 바이트 치환이다. WSL UNC 경로에서 배포판을 읽어 계정 환경 준비와 이름 생성 실행 대상 모두에 전달한다. SSH·네이티브 분기는 유지한다. main 스크립트의 추가 바이트만큼 bootstrap 들여쓰기를 줄여 파일 크기·ASAR 오프셋을 보존하고 main 스크립트 무결성 해시를 갱신한다.

- 1.4.202: `fCi` 실행 대상 분기. 2026-09-15 로컬 패치와 동일한 결과.
- 1.4.215: `VWi` 실행 대상 분기. 설치본의 기존 WSL 경로 파서 `h.r`를 사용한다. 2026-09-28에 이전 수정이 누락된 것을 확인했다.
- 백업은 `app.asar.bootstrap-wsl-rename.<version>.original`로 버전별 보존한다. 기존 버전 없는 백업도 해시가 일치하면 복구에 사용할 수 있다.

다른 버전에 오프셋을 재사용하지 않는다. 코드와 설치본을 검토하고 실행 대상 분기 및 적용·복구 검사를 통과한 후 지원 데이터를 추가한다. 앱 업데이트는 로컬 패치를 덮어쓸 수 있다.

## 업데이트 후 알림

설치 마법사의 **Orca 패치 누락 감시**를 선택하거나 `windows/install-orca-wsl-monitor.ps1`을 명시적으로 실행하면 현재 Windows 사용자의 예약 작업 `MuRing-Orca-WSL-Patch-Monitor`를 등록한다. 로그인 시와 5분마다 확인하며 관리자 권한·앱 종료·자동 패치·업데이트 차단은 수행하지 않는다.

감시 스크립트와 검증 데이터는 `%LOCALAPPDATA%\MuRingDevSetup\OrcaPatchMonitor`에 복사하므로 Orca 업데이트 이후에도 유지된다. 지원 데이터가 추가되면 설치 스크립트를 다시 실행해 갱신한다.

- 검증된 패치본: `patched`, 알림 없음.
- 검증된 원본: `patch-missing`, 재적용 필요 알림.
- 알 수 없는 파일: `unverified`, 검토 필요 알림. 공식 수정 포함 여부를 단정하지 않는다.
- 미설치: `not-installed`, 알림 없음.

새 해시마다 Windows 알림 영역의 풍선 알림을 한 번 요청한다. Windows 알림 설정에 따라 표시가 억제될 수 있으므로 `status.json`에도 결과를 남긴다. `-Quiet` 검사는 알림을 소비하지 않는다. 업데이트 중 파일 변경·읽기 오류는 다음 주기에 재시도한다.

제거: `powershell -NoProfile -File windows\install-orca-wsl-monitor.ps1 -Remove`. 진단 파일은 남는다.

검사: `tests/orca-wsl-rename.ps1 -OriginalArchive <검증된 원본> -Version 1.4.215` (기본 1.4.202). 임시 폴더에서 적용·백업·복원·손상/미지원/잠금 거부 및 감시 상태를 확인한다.

마법사는 `install-orca-wsl-monitor.ps1 -Check`로 예약 작업의 계정·실행 설정·활성 트리거와 설치 스크립트·검증 데이터의 해시를 확인한다. 비활성화되거나 파일이 오래됐으면 다시 설치한다. 감시 완료는 패치 적용 완료와 별개다. 선택 해제는 기존 감시를 제거하지 않는다. `tests/orca-wsl-monitor.ps1`은 격리된 예약 작업으로 설치·반복·손상 감지·재설치·제거를 검증한다.
