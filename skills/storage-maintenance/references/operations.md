# 저장공간 진단·관리

Python 3.10+와 Linux의 GNU du/df/findmnt/git, WindowsPowerShell 5.1을 사용한다. Python은 WSL에서 Windows 수집기를 호출한다. WindowsPowerShell의 출력은 UTF-8 JSON이며 스크립트는 UTF-8 BOM으로 보관한다. 수집은 파일 내용이 아닌 메타데이터만 읽는다. Windows 파일 크기는 Win32 file ID로 대상 내부 hardlink를 한 번만 세고, reparse point를 따라가지 않는다. 수집 API·ACL 실패는 부분 측정으로 보존한다.

## 진단과 비교

```sh
python3 <scripts>/storage.py scan
python3 <scripts>/storage.py scan --config /절대/경로/config.json
python3 <scripts>/storage.py compare --period day
python3 <scripts>/storage.py compare --period week
```

`--state <상태 폴더>`는 하위 명령 앞에 둔다. 기본 상태 폴더는 `~/.local/state/storage-audit`다. 각 실행은 고유한 `snapshot-*.json`을 남긴다. Linux 내부 여유는 df, 현재 swap은 `/proc/swaps`, Windows 볼륨 여유는 DriveInfo, VHD/swap 파일은 별도 target으로 저장한다. VHD 논리 파일 길이와 `GetCompressedFileSizeW` 할당량은 Linux 내부 사용량과 다르다. 폴더별 합계도 볼륨 여유 감소나 삭제 후 회수량으로 환산하지 않는다.

기본 대상은 Linux `.cache`, `.npm`, `/tmp`와 Windows Temp·Packages·Orca·`.cache` 및 레지스트리에서 확인한 WSL VHD다. 사용자 `.wslconfig`의 swapFile와 Temp 1단계 하위의 정확한 `swap.vhdx`만 별도 발견한다. 이는 진단 대상이며 삭제 후보가 아니다. 더 넓은 조사는 targets에 정확한 경로를 추가한다. `.claude`, `.codex` 진단이 필요하면 크기만 측정하고 관리 후보로 넣지 않는다.

Windows 측정은 네이티브 수집기의 대상별 메타데이터 순회와 제한시간을 사용한다. 완료 전에는 1초 간격으로 Windows Temp의 `storage-audit-<UUID>.json` 요약 checkpoint를 기록한다. Linux 호출기는 최대 대상 제한시간+10초 후 수집기를 중단하고 checkpoint를 부분 결과로 읽는다. 수집기가 종료되기 전 쓰지 못한 범위는 미상이다. 이 요약 파일은 자동 삭제하지 않는다. 대상 진행은 stderr, 최종 요약은 stdout JSON이다.

폴더가 중첩되거나 대상 간 hardlink가 있을 수 있어 `totals`는 null이다. 대상 내부 중복 제거와 대상 간 합산 금지를 구분한다. 최신 스냅샷보다 1일/7일 이전의 가장 가까운 스냅샷을 기준으로 비교한다. 정확히 그날 측정한 값이 아니면 시각을 함께 보여준다. 메서드가 다르거나 한쪽이 부분 측정이면 증가량을 계산하지 않는다. `--current`·`--previous`로 같은 스키마의 스냅샷을 명시할 수도 있다. 과거 반올림된 일회성 JSON을 현재 정밀 스냅샷으로 위장하지 않는다.

## 설정과 보존 정책

```json
{
  "version": 1,
  "timeout_seconds": 30,
  "low_free_gib": 20,
  "growth_gib": 5,
  "targets": [{"platform": "linux", "path": "/tmp/example-build", "kind": "directory"}],
  "cleanup_roots": [{"platform": "linux", "path": "/tmp"}],
  "retention": {"min_age_days": 14, "keep_latest": 2, "keep_rollback": 1},
  "candidates": [{
    "platform": "linux", "path": "/tmp/example-build",
    "classification": "agent_temp", "group": "example-test-builds",
    "owner_verified": false, "owner_task_completed": false, "regenerable_verified": false, "provenance": "소유 작업과 생성 근거를 확인해서 적는다",
    "recreation_cost": "재빌드에 필요한 시간·네트워크·의존성",
    "requires_app_exit": true, "current": false, "rollback": false
  }]
}
```

예시 보존 수치는 삭제 승인이 아니다. 최소 나이는 대상 내부에서 가장 최근 수정된 항목을 기준으로 한다. 그룹별 최신 수정 시각 순으로 `keep_latest`개와 명시적인 rollback 중 `keep_rollback`개를 보존한다. 알 수 없는 수정 시각은 보존 쪽으로 정렬한다. 버전 문자열을 추측해 순서를 정하지 않는다. 현재 사용 버전은 `current: true`로 무조건 보존한다. 실제 최신 릴리스·롤백본과 inventory가 맞는지 계획을 검토한다.

후보 분류는 `agent_temp`, `old_build`, `unused_version`, `cache`만 허용한다. `owner_verified`는 경로 접두사만 보고 true로 쓰지 않는다. 캐시의 비활성 하위 항목을 확인하고 정확히 지정한다. `cleanup_roots`는 허용 경계이며 root 자체를 지우지 않는다. glob·상대경로·상위 경로·UNC·Windows ADS는 거부한다. Windows 프로젝트 안의 산출물은 네이티브 backend가 Git 소유를 완전 검증하지 않으므로 보수적으로 거부한다. 해당 산출물은 소유 프로젝트의 적절한 도구로 별도 승인 후 처리한다.

## 계획, 승인, dry-run, 실행

```sh
python3 <scripts>/storage.py plan --config config.json --output plan.json
python3 <scripts>/storage.py apply --plan plan.json
python3 <scripts>/storage.py apply --plan plan.json --approval approval.json
```

두 apply 예시는 삭제하지 않는다. 승인은 계획을 보여준 뒤 받은 사용자 동의만 기록한다. 승인 파일 예시:

```json
{
  "approved": true,
  "plan_digest": "계획의 digest",
  "items": [{
    "platform": "linux", "path": "/tmp/example-build",
    "logical_bytes": 1234, "fingerprint": "해당 measurement의 fingerprint",
    "inactive_confirmed": true, "app_exit_confirmed": true
  }]
}
```

`inactive_confirmed`는 활성 프로세스·열린 핸들·작업 소유자를 확인한 사실이다. 앱 종료 동의만 있고 실제 종료를 확인하지 않았으면 true로 쓰지 않는다. 필요할 때만 별도 앱 종료 승인을 요청한다. WSL/VM 종료는 여기서 수행하지 않는다. 계획은 24시간 후 만료한다. 승인 파일과 대상 지문이 맞지 않으면 재진단·재승인한다.

명시적인 삭제 승인 후에만 동일 명령에 `--execute`를 붙인다. apply는 먼저 승인 allowlist 전체를 검사하고, 각 항목을 삭제 직전 다시 확인한다. Linux는 symlink를 따라가지 않는 디렉터리 FD와 unlink/rmdir, Windows는 reparse 경유를 차단한 파일 핸들로 삭제한다. hardlink가 있는 삭제 후보는 회수량·소유 판단이 모호해 거부한다. 삭제 중 오류는 `partial`로 남기고 다음 항목을 중단한다. 삭제는 트랜잭션 복구가 아니며 일부 파일이 삭제될 수 있다. 활동이 확인되지 않은 폴더는 실행하지 않는다. 사용자 파일을 테스트 fixture로 쓰지 않는다.

Linux에서 같은 사용자 프로세스의 `/proc` 정보도 읽을 수 없으면 비활성으로 추정하지 않고 apply를 거부한다. 소유자에게 실제 사용 상태 확인을 요청하되 도구의 거부를 무시하는 옵션을 추가하지 않는다. 실제 파일은 실행 중인 다른 작업과 동시에 변경하지 않으며, 지문은 내용 해시가 아닌 메타데이터 지문이다.

## 예약과 WSL compaction

`schedule-plan --period day|week --config config.json`은 실행할 read-only scan 명령을 JSON으로 보여준다. 자동화는 아직 설치되지 않는다. 사용자가 주기·대상·허용 실행 환경을 승인한 후 OS의 사용자 예약 기능에 이 명령만 등록한다. WSL 부팅이 필요한 Windows 예약은 그 영향도 승인받는다. 예약에 plan 승인이나 apply를 포함하지 않는다. 비활성화·등록 확인도 같은 OS에서 수행한다.

compaction은 apply에서 항상 거부하는 VHD 작업이다. 모든 WSL 관련 작업과 Docker/VM 중단 동의, 정확한 배포판·VHD 위치, 충분한 백업 공간과 실제 복원 가능한 백업을 확인한다. 그 뒤 별도 Windows 터미널에서 공식 지원 절차를 선택한다. 현재 WSL 세션에서 shutdown이나 압축을 자동 실행하지 않는다. 중단·백업·압축 승인은 일반 캐시 정리 승인과 구분한다. 완료 후 Windows 실제 할당량과 내부 df를 다시 확인한다.

근거: [WSL 디스크 관리](https://learn.microsoft.com/en-us/windows/wsl/disk-space), [GetCompressedFileSizeW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getcompressedfilesizew). 대안으로 robocopy를 사용할 때는 `/L /XJ /R:0 /W:0 /BYTES`를 쓰며 현지화된 요약 제목으로 숫자를 파싱하지 않는다. 반환 코드 8 이상이나 읽기 실패는 완전한 0바이트 결과가 아니다.

## Ubuntu 임시 산출물·Windows 사용자 Temp 확장

`preserve`는 설정의 `{ "platform": "linux", "path": "/정확한/보존/경로", "root_only": false }` 목록이다. 기본은 하위 전체와 이를 포함하는 상위 후보를 보호한다. 공유 임시 작업 루트만 `root_only: true`로 두면 루트 일괄 삭제를 막으면서 개별 산출물의 검증을 허용한다. 현재 서버·프로젝트 의존성·개발 캐시·AI 작업 로그·KB venv/models·사용 중인 Playwright 런타임은 보존 목록으로 관리한다. 경로 이름만으로 cache라고 추정하지 않는다.

후보의 `owner_task_completed: true`는 소유 작업이 끝났다는 확인, `regenerable_verified: true`는 고유 자료가 없는 재생성 산출물이라는 확인이다. 기존 기록의 `status: deleted`는 현재 존재 여부나 이 세션의 삭제 승인이 아니다. 원래 검사 기록은 provenance로만 보존하고 매번 현재 manifest를 만든다. 계획 형식은 version 2이며 이전 계획은 새 검증 규칙으로 다시 생성해야 한다. 주변 로그를 보존하려면 archive 파일 또는 하위 node_modules 등 정확한 산출물만 후보로 지정한다. symlink 포함 후보는 기존 안전 규칙에 따라 보류하며 우회하지 않는다.

Linux는 cwd/exe/fd뿐 아니라 maps의 열린 fd 없는 매핑도 검사한다. 다른 사용자의 읽을 수 없는 프로세스도 미상이다. Windows 실행파일 경로 검사는 관측 결과만 제공하고, 현재 backend는 전체 핸들 열거를 지원하지 않으므로 비활성을 확정하지 않는다. 이 경우 후보는 보류되고 실제 apply도 건너뛴다. 사용자 확인만으로 이 자동 검사 제한을 덮어쓰지 않는다.

apply 실행은 볼륨 여유의 전후 관측을 `space_before`와 `space_after`에 저장한다. Linux 내부와 Windows host는 별도이며, 동시 쓰기·삭제 때문에 차이를 해당 작업만의 회수량으로 단정하지 않는다. dry-run에는 실제 회수 수치를 만들지 않는다. 중첩 경로·hardlink의 총 회수량 추정은 계속 미상으로 둔다.

## 제한된 프로세스 검사 권한과 Yarn v6 링크

기본 `process_probe`는 `local`이다. 사용자가 프로세스 가시성 확보를 요청한 경우 후보에 `"process_probe": "wsl-root"`를 지정한다. `wsl.exe --distribution <현재 배포판> --user root --exec /usr/bin/python3 -I <process_probe.py> <정확한 경로> <제한시간>`으로 읽기 전용 검사만 실행한다. 로그인 설정·sudoers·ptrace·proc 권한을 바꾸거나 프로세스를 종료하지 않는다. probe에는 삭제 기능이 없고, 실제 unlink는 기존 사용자로 수행한다. 서로 다른 boot ID·mount namespace·대상 device/inode, 비-root 결과, 타임아웃은 모두 미상이다. systemd/sd-pam이라는 이름만으로 검사에서 제외하지 않는다.

여러 Yarn 패키지를 계획할 때 `process_probe_scope`를 정확한 캐시 루트로 지정하면 상위 전체에 대한 계획 시점 검사를 한 번 공유한다. 후보가 그 경로 밖이면 거부한다. apply는 이 캐시를 재사용하지 않고 범위와 대상의 프로세스 참조를 다시 확인한다.

Linux cache 후보에서만 `"symlink_policy": "yarn-v6-bin"`을 사용한다. Yarn 캐시 루트 또는 `v6/npm-…` 패키지 하나를 후보로 삼을 수 있다. `.bin` 링크는 해당 package 내부 일반 파일에 이르는 상대 경로여야 한다. 링크 target 문자열도 지문에 포함하고 삭제 직전에 다시 비교한다. 상위·최종 경로의 symlink를 따라가지 않으며 보호 콘텐츠 규칙은 동일하다. 다른 symlink는 기본 거부한다. 보호 콘텐츠가 있는 패키지는 보존 목록에 남기고 나머지만 분할 계획한다. 보호 경로 예외 규칙을 추가하지 않는다.

근거: [WSL 사용자 지정 실행](https://learn.microsoft.com/en-us/windows/wsl/basic-commands), [Linux proc fd 접근 검사](https://man7.org/linux/man-pages/man5/proc_pid_fd.5.html), [Yarn Classic 전역 캐시](https://classic.yarnpkg.com/lang/en/docs/cli/cache/).
