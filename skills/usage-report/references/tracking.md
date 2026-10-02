# 지속 수집·동기화

Python 3.10+·Git·인증된 기존 KB 원격 저장소가 필요하다. Windows에서 IANA 시간대가 없으면 `python -m pip install tzdata`를 설치한다. 원본 로그는 각 기기에 남고, 공개 가능한 프로젝트 별칭과 원문 없는 수치만 공유한다. 원격 저장소 접근 범위를 설치 전에 확인한다.

아래 `<scripts>`는 이 스킬의 `scripts/`다. 프로그램은 모델을 호출하지 않는다.

```sh
python3 <scripts>/usage_tracker.py init --repo /path/to/muring-kb
```

기본 설정은 `~/.config/ai-workflow/tracking.json`, 상태는 `~/.local/state/ai-workflow/tracking/`, 전용 worktree는 `~/.local/share/usage-sync/`다. `--config`는 하위 명령 앞에 지정한다. 새 기기는 `init`으로 새 기기 ID를 생성한다. 설정 파일을 다른 기기로 복사하여 기기 ID를 재사용하지 않는다. 기존 worktree/등록 경로는 덮어쓰지 않는다.

`projects`에 로컬 절대 경로 또는 저장소 basename → 공통 프로젝트 ID 매핑을 설정한다. 절대 경로는 자기 경로와 하위 경로에 적용하며 가장 긴 일치 경로가 우선한다. 따라서 저장소 아래 별도 앱은 더 구체적인 경로로 분리할 수 있다. 경로 구분자로 경계를 검사하며 Windows 드라이브 경로는 대소문자를 구분하지 않는다. 절대 경로에 일치하지 않을 때만 basename을 쓴다. 실제 경로와 의도한 별칭을 확인한 후 설정하고, 모르는 경로는 `unmapped`로 남긴다. 매핑 변경은 수집 캐시를 무효화한다. 같은 기간·요청 집합의 전후 총량이 같고 프로젝트별 합이 전체와 일치하는지 확인한다. `roots`의 `required=true` 경로 접근 실패는 게시를 보류한다. 도구를 새로 설치하면 해당 경로를 추가하고 `required=true`로 변경한다. Codex/Claude 별도 설정 홈을 사용하는 환경은 실제 로그 경로를 명시한다.

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

작업 시작 시 아래 명령으로 현재 시각과 고유 핸들을 남기고, 종료 시 해당 핸들과 결과 JSON을 전달한다. 시작을 놓쳤다면 지금부터의 구간만 기록하고 앞부분을 추정하지 않는다. 핸들은 현재 작업 맥락에 보관하며 전역 current-task는 사용하지 않는다. 같은 작업을 재개할 때는 같은 작업 ID로 새 핸들을 발급해 구간을 추가한다. 다른 작업으로 전환하거나 기다리는 구간을 제외해야 하면 현재 구간을 먼저 종료한다. 세션이 바뀌면 새 핸들을 만든다.

```sh
python3 <scripts>/usage_tracker.py task-start --tool Codex --id issue-42 --project muring/example
python3 <scripts>/usage_tracker.py task-finish --handle <반환된 handle> --file <결과 JSON>
```

`session-identify --tool Codex|Claude`로 식별만 점검할 수도 있다. Codex는 현재 환경의 `CODEX_SESSION_ID`·`CODEX_THREAD_ID`가 서로 일치하고 설정된 수집 루트의 `session_meta.id`와 일치할 때만 연결한다. 이 환경 변수는 로컬에서 관찰한 식별 수단이며 모든 실행 환경에 있다고 가정하지 않는다. Claude는 현재 세션에서 확인한 `--session-id <ID>` 또는 실제 훅 입력 JSON을 `--hook-input <파일>`로 전달한다. [Claude 훅의 공통 입력](https://code.claude.com/docs/en/hooks#common-input-fields)의 `session_id`·`transcript_path`를 사용하되 로그의 `sessionId`와 대조한다. `--transcript <파일>`로 확인 대상을 제한할 수 있다. 훅을 자동 설치하거나 최신 transcript·cwd·PID만으로 세션을 추정하지 않는다. 서브에이전트 훅·식별 충돌·읽기 실패·출처 프로젝트 미매핑은 미상으로 남긴다.

종료 JSON에는 `id`, 대상 `project`, 아래 결과 필드를 넣고 `sessions`, `intervals`, `since`, `until`은 비우거나 생략한다. 도구가 확인한 출처 프로젝트·가명 세션 키·시작/종료 시각을 `intervals`에 저장한다. 작업 대상과 출처가 달라도 명시한 구간은 연결하며 프로젝트별 사용량은 세션 cwd 기준을 유지한다. 종료 재호출은 기존 작업 결과를 보존하고 새 KB 대조 시도를 기록한다. 여러 작업 구간이 겹친 응답은 중복 배분하지 않고 미분류로 남긴다. 측정 기준은 요청 사용량의 기록 시각이며 첫 호출 전·마지막 종료 호출 후 사용량까지 포함한다고 주장하지 않는다.

과거 기록과 경계를 모르는 결과는 `task --file <파일>`로 기록한다. `session-key`는 ID를 가명화할 뿐 현재 세션임을 검증하지 않는다. 수동 `intervals`는 `{ "session": "<가명 키>", "project": "<출처 별칭>", "since": "<시간대 포함 시각>", "until": "<시간대 포함 시각>" }` 목록이다. 근거로 두 경계를 확인했을 때만 작성하며 `sessions`에는 해당 키만 넣는다. 예전 형식의 `sessions`+`since`+`until`은 동일 프로젝트의 닫힌 구간으로 지원한다. 한쪽 경계라도 없으면 세션 전체에 연결하지 않는다. 기존 무경계 기록은 보존하되 사용량은 미상으로 둔다. 전체 대화 재조회·세션 전체의 여러 작업 일괄 연결은 하지 않는다. 연결 없는 결과 JSON 예시:

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

KB CLI는 수집 설정이 해당 KB를 가리킬 때만 검색 방식·결과 개수·소요 시간·오류 개수를 로컬에 기록한다. 검색어는 저장하지 않는다. 실제 적용은 기존 `usage/events/`의 명시적 기록에서 원문 근거를 제외하고 가져온다. 현재 핸들의 `kb-search`로 project/task를 연결하고 읽고 판단한 문서는 선택 activity.knowledgeDecisions로 보고한다. 저장된 근거 있는 판단에서만 kb_selection이 멱등 생성된다. `task-finish`는 읽기 전용 KB 이력 대조 결과도 반환한다. 형식과 재시도/명시적 기록은 [KB 판단과 종료 대조](activity.md#kb-판단과-종료-대조)를 따른다. 검색 언급·실행·문서 선택·실제 적용은 서로 다른 증거이며, 선택이 보고되지 않으면 미상이다.

## 오류·정정

`status`와 로컬 `last-scan.json`, `run.json`, `sync.json`을 확인한다. 48시간 넘게 갱신되지 않은 기기는 주의를 표시한다. 수집 상태가 나쁘면 기존 정상 상세 자료를 보존한다. 기록 없음은 사용량 0의 증거가 아니다.

원본 감소 후보는 로컬 `quarantine/`에 남긴다. 사용자가 실제 원본 정정/대체임을 확인한 경우에만 `accept-correction --source <가명키> --candidate <후보 전체의 canonical JSON SHA256> --reason verified_source_correction|verified_source_replacement`로 수용한다. 확인하지 않은 수치 감소를 자동 승인하지 않는다. 정정 근거와 이전·새 해시를 Git 데이터에 남긴다.

정기 수집의 월별 크기 기록은 로컬 상태에, 일별 크기 기록은 기기 데이터의 `storage/`에 남는다. Git 크기는 같은 저장소의 다른 브랜치 자료도 포함한다. 초기 4주 증가량을 확보하기 전 연간 크기를 확정하지 않는다. Git에서 파일을 지워도 과거 이력의 공간은 회수되지 않는다.

세부 토큰 필드의 `observed_fields`와 보고서의 `field_observation_counts`는 누락된 추론/캐시 필드를 실제 0과 구분한다. 합계는 관측된 값의 합이며 미관측 항목의 전체 사용량을 추정하지 않는다.

## 블로그 집계 내보내기

`usage_publish.py --worktree <usage-data checkout> --revision <전체 source SHA> --sequence <증가하는 작업 순번> --output <임시 JSON> --improvements <개선 기록 JSON>`은 기존 집계 함수를 호출해 블로그용 연도별 요약을 생성한다. 세션 키·원문 로그·명령 인수는 전송하지 않는다. 새 수집이나 AI 호출은 하지 않는다.

`--send`는 명시적으로 연결한 HTTPS `AI_USAGE_INGEST_URL`과 비밀 환경변수 `AI_USAGE_INGEST_KEY`를 사용한다. private KB의 예약 workflow가 실행하며 일반 로컬 수집기에 자동 전송을 추가하지 않는다. schema/metrics 불일치·원본 무결성 오류는 게시하지 않고 종료한다. 예약 workflow와 배포 설정은 해당 KB·블로그 운영 문서를 따른다. 승인된 HTML 렌더러·양식은 변경하지 않는다.


## Git 기반 일일 발행

선택 `publisher.mode=git-workflow` 설정과 `publish-retry`/`publish-status`, exporter ACK·receipt 계약은 [Git 발행 안내](git-publish.md)를 따른다. sync 성공의 실제 revision을 main workflow에 연결하고 검증된 실행·receipt로 DB 결과를 확인한다. 기존 private task의 presentation/activity/knowledgeReviews는 검증 후 집계·전송하고 원본 및 공개 projection 경계를 보존한다. 기존 작업 기록의 직접 편집·생성 권한을 추가하지 않는다.


## 작업 표시 presentation

원본 계약은 mublog `src/lib/ai-usage.ts`의 `taskPresentationSchema`다. 기존 task와 payload는 presentation 없이 그대로 유효하다. 새 필드는 선택이지만 지정했다면 아래 일곱 키 모두 필요하다. 추가 키는 허용하지 않는다.

```json
{
  "title": "작업 결과 표시 개선",
  "summary": "검사와 후속 작업을 구분해 기록했다.",
  "occurredAt": null,
  "checks": [{"title": "회귀 검사", "method": "격리 fixture에서 기존·신규 기록을 확인", "result": "pass", "reason": null}],
  "followUps": [{"title": "운영 배포", "status": "delegated", "note": "소유 프로젝트 세션에서 수행"}],
  "knowledge": [],
  "evidence": ["로컬 검사 결과"]
}
```

title·검사/후속 제목·knowledge.document는 300자, summary는 2000자, method/reason/note/evidence 각 항목은 1000자 이하다(수신부와 같은 UTF-16 길이). checks.result는 pass/fail/not_run/unknown, followUps.status는 pending/delegated/unknown, knowledge.usage는 reference/applied다. reason은 null 가능하다. occurredAt은 시간대 포함 ISO datetime 또는 null이며 근거 없는 시각을 만들지 않는다. 검사하지 않은 일이나 위임한 후속 작업을 통과한 검사로 기록하지 않는다. 원본 verification을 삭제·번역 덮어쓰기하지 않는다. 외부 공개 가능하도록 검토한 한국어 요약만 쓰며 원문 로그·인증·민감 경로는 넣지 않는다.

보완 형식은 `{ "project": "프로젝트 별칭", "id": "작업 ID", "presentation": { ... } }`다. 데이터 worktree의 `task-presentations`에 digest([project,id]) 이름으로 private usage-data 전용 worktree에 보관한다. 집계는 검증 후 메모리에서만 병합하며 원본 task를 변경하지 않는다. 원본 presentation과 보완 내용이 같으면 허용하고, 다르면 오류다. 원본 task가 기기 간 충돌한 경우에도 보완으로 승자를 선택하지 않는다. 없는 대상·잘못된 파일명·symlink·계약 위반은 명확한 오류다. guard는 정확한 digest JSON 경로, 형식, 대상 존재, 원본/보완 일치를 작업 트리와 Git index에서 검증한다. 검증된 sidecar는 자기 기기의 task와 함께 private usage-data 브랜치 sync의 add 대상에 포함된다. 같은 sidecar에 대한 동시 수정은 보류하며, 다른 파일끼리 원격 병합돼도 의미상 충돌·없는 대상이면 push 전에 실패한다. 이때 이미 생성한 로컬 데이터 커밋과 병합 결과는 보존하므로 근거를 확인해 수동 해결해야 한다. 보완 파일을 public 코드 저장소로 복사하지 않는다. 발행기는 검증된 presentation만 선택적으로 전달하며 schema 1 / usage-v1은 유지한다.

## 실제 KB 대조 이력 전달

종료/재대조 시 결과를 `devices/<device>/knowledge-reviews/<attempt-id>.json`에 불변 저장한다. aggregate와 private publisher는 task identity로 묶은 선택 `knowledgeReviews` 이력을 보존한다. 기존 task 원본·activity sidecar·presentation과 검증 기록은 유지한다. 저장·staged·원격 병합 뒤 같은 ID의 다른 내용/삭제·변형/대상 누락을 거부한다. 대조 결과를 수신하는 구체적인 계약·합성 fixture는 [knowledge-reviews](knowledge-reviews.md)를 따른다.
