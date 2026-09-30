# 지속 수집·동기화

Python 3.10+·Git·인증된 기존 KB 원격 저장소가 필요하다. Windows에서 IANA 시간대가 없으면 `python -m pip install tzdata`를 설치한다. 원본 로그는 각 기기에 남고, 공개 가능한 프로젝트 별칭과 원문 없는 수치만 공유한다. 원격 저장소 접근 범위를 설치 전에 확인한다.

아래 `<scripts>`는 이 스킬의 `scripts/`다. 프로그램은 모델을 호출하지 않는다.

```sh
python3 <scripts>/usage_tracker.py init --repo /path/to/muring-kb
```

기본 설정은 `~/.config/ai-workflow/tracking.json`, 상태는 `~/.local/state/ai-workflow/tracking/`, 전용 worktree는 `~/.local/share/usage-sync/`다. `--config`는 하위 명령 앞에 지정한다. 새 기기는 `init`으로 새 기기 ID를 생성한다. 설정 파일을 다른 기기로 복사하여 기기 ID를 재사용하지 않는다. 기존 worktree/등록 경로는 덮어쓰지 않는다.

`projects`에 로컬 cwd 또는 저장소 basename → 공통 프로젝트 ID 매핑을 설정한다. 모르는 경로는 `unmapped`로 남는다. `roots`의 `required=true` 경로 접근 실패는 게시를 보류한다. 도구를 새로 설치하면 해당 경로를 추가하고 `required=true`로 변경한다. Codex/Claude 별도 설정 홈을 사용하는 환경은 실제 로그 경로를 명시한다.

```sh
python3 <scripts>/usage_tracker.py run
python3 <scripts>/usage_tracker.py report --preview --year 2026
python3 <scripts>/usage_tracker.py status
```

`run`은 변경된 파일만 재해석하고 최초 최근 30일에 걸친 주부터 보존한다. 최근 주뿐 아니라 오래된 파일 변경도 확인한다. 원본과 같은 세션·응답은 중복 제거하며, 식별 불확실성·충돌·미분류는 보고한다. `devices/<기기>/<연도>/<월요일>/`에 주간 상세 수치와 그룹별 합계, `tasks/`에 명시적 작업 기록을 저장한다. 매니페스트 교체 전에는 기존 정상 세대가 유효하다. 예전 세대와 Git 이력은 삭제하지 않는다. 파일 수집은 증분이지만 저장된 전체 상세 수치의 검증·집계는 다시 수행한다.

## 양식 승인과 자동화

최초 HTML을 사용자에게 보여 주고 **양식에 대한 명시적 승인**을 받은 뒤, `report --preview`가 출력한 fingerprint로 승인한다. 구현 승인·자동 동기화 승인을 양식 승인으로 대신하지 않는다. fingerprint에는 템플릿·렌더러·지표 버전이 포함된다.

```sh
python3 <scripts>/usage_tracker.py approve --fingerprint <확인한-fingerprint>
python3 <scripts>/usage_tracker.py schedule --enable
```

`approve`는 KB의 `archive/reports/usage/template-approval.json`에 기록만 남긴다. 해당 파일·코드·템플릿의 일반 브랜치 커밋은 별도 요청 범위다. 다른 기기도 검토된 동일 버전의 코드와 양식을 받아야 한다.

`schedule`만 실행하면 파일을 준비하고 활성화하지 않는다. Linux/WSL은 사용자 systemd, Windows는 작업 스케줄러, macOS는 launchd가 15분마다 KST 실행 기한을 확인하고 하루 한 번 수집한다. 타이머는 꺼진 환경을 강제로 시작하지 않는다. Windows/macOS 등록은 해당 OS에서 별도 검증이 필요하다.

일일 수집과 시작 시 누락 보충 후 승인된 HTML도 재생성한다. 따라서 월요일 보고 외에도 현재 주·늦게 도착한 자료가 갱신된다. 조회 연도 기본값은 현재 KST 연도다. 작년 주에 포함되는 1월 초 기록은 `--year <작년>`으로 확인한다. 생성 JSON/HTML은 무시된 `archive/reports/usage/generated/`에 있다.

```sh
python3 <scripts>/usage_tracker.py run --sync
python3 <scripts>/usage_tracker.py sync
```

자동 Git 작업은 전용 worktree·`usage-data`·자기 기기 JSON 경로로 제한한다. 일반 작업 폴더의 파일을 staging하지 않는다. push 실패 시 로컬 커밋을 보존하고 이후 재시도한다. 강제 push나 충돌 자동 해결은 하지 않는다. 동일 기기 ID 동시 사용·임의 수정·충돌은 수동 점검한다.

## 작업 완료·검증 기록

이미 확인한 작업 맥락으로 짧은 JSON을 작성해 `task --file <파일>`로 기록한다. 전체 대화 재조회나 매 작업 사용자 설문을 하지 않는다. 안정된 작업 ID를 후속 작업에서도 재사용한다. 같은 세션에 여러 작업이 있으면 `since`/`until`(끝 제외)을 지정한다. 연결할 수 없는 사용량은 미분류다.

세션 원본 ID를 알고 있을 때만 `session-key --tool Codex|Claude --id <ID>`로 가명 키를 얻는다. 모르면 `sessions: []`로 남긴다. 작업 기록 예시:

```json
{
  "id": "issue-42", "project": "muring/example", "type": "bugfix",
  "status": "completed", "sessions": [],
  "verification": [{"name": "regression suite", "result": "pass"}],
  "rework": null, "rework_reason": null, "parent_task": null,
  "improvements": [], "kb_documents": [], "evidence_kind": "explicit_record"
}
```

상태는 `completed|partial|in_progress|stopped`, 검증 결과는 `pass|fail|not_run|unknown`이다. 추측한 작업 난이도·성공률·재작업 사유는 기록하지 않는다. 원문·민감한 경로를 설명에 넣지 않는다. 여러 기기의 동일 작업 기록이 상충하면 자동 승자를 선택하지 않는다.

KB CLI는 수집 설정이 해당 KB를 가리킬 때만 검색 방식·결과 개수·소요 시간·오류 개수를 로컬에 기록한다. 검색어는 저장하지 않는다. 실제 적용은 기존 `usage/events/`의 명시적 기록에서 원문 근거를 제외하고 가져온다. 문서를 실제 선택한 경우 `kb-selection --document <KB 상대 경로> --task <작업 ID>`로 보고한다. 검색 언급·실행·문서 선택·실제 적용은 서로 다른 증거이며, 선택이 보고되지 않으면 미상이다.

## 오류·정정

`status`와 로컬 `last-scan.json`, `run.json`, `sync.json`을 확인한다. 48시간 넘게 갱신되지 않은 기기는 주의를 표시한다. 수집 상태가 나쁘면 기존 정상 상세 자료를 보존한다. 기록 없음은 사용량 0의 증거가 아니다.

원본 감소 후보는 로컬 `quarantine/`에 남긴다. 사용자가 실제 원본 정정/대체임을 확인한 경우에만 `accept-correction --source <가명키> --candidate <후보 전체의 canonical JSON SHA256> --reason verified_source_correction|verified_source_replacement`로 수용한다. 확인하지 않은 수치 감소를 자동 승인하지 않는다. 정정 근거와 이전·새 해시를 Git 데이터에 남긴다.

정기 수집의 월별 크기 기록은 로컬 상태에, 일별 크기 기록은 기기 데이터의 `storage/`에 남는다. Git 크기는 같은 저장소의 다른 브랜치 자료도 포함한다. 초기 4주 증가량을 확보하기 전 연간 크기를 확정하지 않는다. Git에서 파일을 지워도 과거 이력의 공간은 회수되지 않는다.

세부 토큰 필드의 `observed_fields`와 보고서의 `field_observation_counts`는 누락된 추론/캐시 필드를 실제 0과 구분한다. 합계는 관측된 값의 합이며 미관측 항목의 전체 사용량을 추정하지 않는다.
