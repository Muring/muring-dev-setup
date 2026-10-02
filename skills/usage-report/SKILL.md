---
name: usage-report
description: Codex·Claude 로컬 토큰 집계, 여러 기기 지속 수집·동기화, 작업 결과와 효율 검토에 사용한다. 청구 금액이나 구독 잔여량 조회는 아니다.
---

Claude `/usage-report`, Codex `$usage-report`. 함께 전달한 입력을 기간·프로젝트 등의 조건으로 해석한다.
이 스킬의 `scripts/usage_report.py`를 실행한다. 대화 원문 전체를 모델에 읽히지 않는다.

```bash
python3 <이-스킬-경로>/scripts/usage_report.py --week --by project,tool,session --json
```

기본 기간은 Asia/Seoul 월요일 00:00부터 현재까지다. 과거 검토는 `--since 2026-09-14 --until 2026-09-21`처럼 종료 제외 범위를 지정한다. `--timezone`, `--limit`도 지원한다.
“최근 일주일”은 월요일 기준 대신 `--days 7`을 쓴다. 특정 도구 요청에는 `--tool codex` 또는 `--tool claude`로 로그를 읽기 전부터 범위를 좁힌다. 효율 분석에는 `--diagnostics`를 추가해 Codex·Claude의 입력 크기·큰 도구 출력·잘림 표시·동일 호출 반복을 집계한다. 원문·명령 인수는 출력하지 않으며 문자 수를 토큰 수로 환산하거나 반복 호출을 곧바로 낭비로 판정하지 않는다.

```bash
python3 <이-스킬-경로>/scripts/usage_report.py --tool codex --days 7 --by project,model,day,session --diagnostics --json
```
기본은 현재 사용자 홈이다. 추가 PC/Windows 로그는 `--home /home/me --home /mnt/c/Users/Me`로 명시하거나 `${XDG_CONFIG_HOME:-~/.config}/ai-workflow/usage.json`의 `{"homes":["/home/me","/mnt/c/Users/Me"]}`에 저장한다. `CODEX_HOME`, `CLAUDE_CONFIG_DIR`도 반영한다. 다른 계정의 홈을 임의로 탐색하지 않는다.

- 입력 전체·캐시 읽기·캐시 읽기 제외 입력·출력을 구분한다. cache write는 입력에, reasoning은 출력에 이미 포함된다.
- 응답 중복을 제거하며 Codex의 요청별 usage를 우선한다. 오래된 누적 로그의 reset/기준값 누락과 접근 실패는 warnings에 표시된다.
- Claude cost-state와 내부 보조 요청, 이미지 생성 백엔드 비용은 요청 기록과 일관되게 대조할 수 없어 추가하지 않는다. 계정의 청구 총량이나 구독 한도 소모로 단정하지 않는다.
- 프로젝트는 cwd로 분류한다. 다른 저장소를 읽은 작업까지 정확히 구분한 값이 아니다. 상위 세션의 원인이 필요하면 해당 기간·세션의 도구 메타데이터부터 좁혀 조사한다.
- 최적화는 호출 수·불필요한 맥락·실패 후 재작업을 기준으로 제안하고, 정상적인 테스트·사용자가 요청한 대안 비교를 일괄 낭비로 분류하지 않는다. 절감률은 전후 측정으로 검증한다.

## 지속 추적과 작업 결과

여러 기기 수집·전용 브랜치 동기화·HTML 양식·정기 실행·작업 결과 기록은 [지속 수집 안내](references/tracking.md)를 읽고 `scripts/usage_tracker.py`를 사용한다. 집계는 로컬 프로그램으로 처리하고 분석에 원문 전체를 넣지 않는다. 설치·형식 승인이 없는 환경에서 임의로 자동화를 활성화하지 않는다.

활성 일일 경로는 [Git 기반 발행 계약](references/git-publish.md)의 opt-in `publisher.mode=git-workflow`다. 하루 1회 수집·검증된 usage-data sync 성공 후 main workflow를 호출하고, 정확한 run/receipt를 검증해 접수·실행·DB 결과를 구분한다. 실패·미확인은 성공으로 바꾸지 않으며 실제 전송·예약 전환은 별도 승인 범위다. 이전 원본 DB 전달과 서버 정정은 기존 변경·검증 근거로 보존하며 현재 운영 대상이 아니다. Git 정정의 승인·감사 연결은 미완료 후속 범위다.

추적 설정이 있는 환경에서는 독립 작업 시작 시 `task-start --tool Codex|Claude --id <작업 ID> --project <대상 별칭>`으로 시작 경계와 고유 핸들을 기록하고, 종료 시 `task-finish --handle <그 핸들> --file <결과 JSON>`으로 이미 확인한 유형·상태·검증·재작업·KB 적용을 기록한다. 반환된 핸들은 해당 작업 맥락에 보관한다. 전역 current-task 파일을 만들거나 다른 터미널의 핸들을 재사용하지 않는다.

Codex는 `CODEX_SESSION_ID`·`CODEX_THREAD_ID`를 로컬 `session_meta.id`와 대조한다. Claude는 현재 세션에서 확인한 ID를 `--session-id`로, 또는 실제 훅 입력 파일을 `--hook-input`으로 전달하고 로그의 `sessionId`와 대조한다. 최신 파일·cwd만으로 현재 세션을 추측하지 않는다. 식별 불가면 `sessions: []`, 시작을 놓쳤으면 확인 가능한 시점부터만 기록한다. 별도 구간마다 새 핸들을 쓰며 작업 대상 프로젝트와 세션 출처 프로젝트는 구분한다. 상세 입력·과거 기록 조건은 지속 수집 안내를 따른다.

`task --file`은 경계를 모르는 결과나 근거가 있는 과거 기록에 사용한다. 시작·종료가 모두 확인되지 않은 연결은 집계에서 미상으로 남긴다. 세션 전체를 여러 작업에 일괄 연결하지 않는다. 데이터만 전용 worktree에 기록하며 일반 프로젝트 변경을 자동 커밋하지 않는다.


## 작업 표시용 기록

선택 `presentation`은 한국어로 확인한 작업 제목·요약·검사 방법과 결과를 기록한다. 원본 `verification`은 유지한다. 실제 실행한 검사는 `checks`, 아직 할 일과 다른 세션에 위임한 일은 `followUps`로 구분한다. 실행하지 않은 검사는 `not_run`, 결과 미상은 `unknown`이며 완료·통과로 바꾸지 않는다. `occurredAt`은 근거가 있는 시간대 포함 시각 또는 `null`이다. 날짜·실패 이유·개선 효과를 추정하지 않는다. KB는 단순 참고와 검증된 적용을 구분한다.

계약과 예시는 [지속 수집 안내](references/tracking.md#작업-표시-presentation)를 따른다. 원본 task의 선택 presentation 또는 private usage-data worktree의 `task-presentations/<digest([project,id])>.json` 보완 파일을 지원한다. 보완 파일은 집계 시에만 병합하며 원본 task를 덮어쓰지 않는다. 동일 내용은 허용하지만 파일명·대상 불일치, 내용 충돌, 없는 대상, 형식 오류는 수정 근거 확인 전까지 실패로 유지한다. 개인 보완 파일은 public 코드 저장소에 복사하지 않는다. 검증된 보완 파일은 기존 task와 함께 설정된 private `usage-data` 전용 브랜치에서만 guard/sync 대상으로 취급한다. 작업 트리와 index를 모두 검증하며 원격 병합 후에도 원본·보완 충돌을 검사한다. 실제 sync·발행은 해당 세션의 승인 범위를 따른다.


## 작업 종료 시 activity 기록

향후 독립 작업 종료 JSON에는 확인한 목적·수행 내용·실제 AI 역할·사람의 판단/수정·결과·검사와 미확인 범위·후속 일·KB 참고/적용을 선택 `activity`로 기록한다. 입력 계약은 [activity 기록 안내](references/activity.md)를 따른다. 기존 verification/presentation은 보존한다. 모든 필수 키를 두되 모르는 값은 null, 확인한 항목 없음은 빈 배열로 구별한다. 활동 근거를 짧은 private 출처로 연결하고 장문 대화 원문을 복사하지 않는다.

신규 작업은 `task-start`에서 수행 시작일을 함께 수집한다. activity를 직접 작성할 때도 반환된 시작 경계와 task-runs 근거로 timing을 기록한다. `task-finish`는 입력·기존 원본·sidecar에 activity가 모두 없으면 관측한 시작일을 date로 자동 보존한다. 명시적 미상이나 기존 날짜는 덮어쓰지 않으며 시작 기록이 없는 과거 작업에는 저장일을 대신 넣지 않는다.

category는 work_execution/kb_maintenance/mixed/unknown 중 실제 작업 목적에 따라 명시한다. 프로젝트가 KB이거나 토큰·검사 결과가 있다는 이유로 유형·AI 기여·효과를 추정하지 않는다. 과거 activity 자동 채우기는 하지 않는다. 효과는 측정 방법과 전후 값 또는 사용자 확인 근거가 있을 때만 기록한다. 성공률·기여도 점수·효과 합계를 만들지 않는다.

확인한 수행일만 있으면 timing.precision=date와 occurredOn을 쓰고 자정 시각을 만들지 않는다. 시각까지 확인됐을 때 timestamp를 쓴다. 별도 사용자 예외 지시가 없다면 ID에서 읽은 날짜는 labelDate로만 남기고 수행일은 unknown으로 유지한다. 저장 시각·세션 연결로 작업 날짜를 채우지 않는다. 공개 사례는 별도 작성한 projection과 사용자 검토 근거가 필요하며 private 상세 복사·자동 공개·배포를 하지 않는다. 공개 승인 상태 변경도 명시적인 검토 근거를 기록한다. KB 후보 등록은 기존 절차와 별개다.

## 프로젝트 간 인계 기록

실제로 승인된 인계는 `activity.handoffs`에 기록한다. 최초 발신에서 인계 ID를 만들고 from/to/request와 함께 상대에게 전달한다. 재전송과 수신·착수·결과에는 같은 ID를 쓰며, 상대 작업 ID가 미확인이면 null로 둔다. 수신 측은 전달된 from/to/request를 그대로 보존하고 실제 자신이 수신·착수·완료한 이벤트와 근거를 추가한다. 인계가 끝났다고 기존 보류/실패 이력을 지우지 않는다.

도구 `input_accepted`는 transport의 `dispatch_accepted`일 뿐 수신 완료가 아니다. 상대 응답 없이 received/started/completed로 기록하지 않는다. 실제 결과의 reportedBy와 출처를 보존하고 completed/failed에는 결과·산출물·검증 범위를 남긴다. 이 필드 전체는 private 전용이다. 기록 절차는 전송 권한을 부여하지 않으며 실제 인계·메시지 전송은 현재 사용자 승인 범위를 따른다. 상세 형식·충돌 처리는 [인계 기록](references/activity.md#프로젝트-간-인계)을 따른다.

## KB 검색·선택·적용 판단 대조

현재 작업의 `task-start` 반환값에 있는 project/id와 handle을 보관한다. 관련 KB 검색은 `kb-search --handle <핸들> --keyword <검색어>`로 실행한다. 이 명령은 확인한 project/id를 KB CLI의 `--task-project`, `--task-id`로 전달하며, `--project`는 별도의 검색 필터다. 기본 KB telemetry와 tracker의 repo/state가 다르면 연결을 중단한다. 검색어·snippet은 상태 파일에 기록하지 않는다. 검색 JSON의 telemetry.searchId는 실제 문서를 읽고 선택한 경우에만 사용한다.

작업 종료 activity에는 선택 `knowledgeDecisions`로 문서·선택 경로·검색 출처·판단·이유·적용 내용·검증·근거를 기록한다. 누락/null은 미수집, []는 확인한 판단 대상 없음이다. 알려진 문서를 바로 읽었으면 direct와 빈 searchRefs를 쓴다. 검색 반환만으로 선택/적용/미사용을 추정하지 않는다. applied는 실제 적용 내용과 pass 또는 fail 검사 근거가 필요하며 실패도 실제 적용으로 남긴다. 구체적 형식은 [activity 기록 안내](references/activity.md#kb-판단과-종료-대조)를 따른다.

`task-finish`는 저장한 원본/sidecar를 검증하고 KB의 읽기 전용 knowledge-review를 호출한다. 반환 knowledgeReview와 로컬 `knowledge-reviews/<handle>.json`에서 이력 일치, 적용 이력 누락, 미적용, 판단 미상, 검색 연결 오류, 대상 외 문서, 충돌을 확인한다. unavailable/failed는 대조 미완료이며 통과가 아니다. `knowledge-review --handle <핸들>`로 재시도한다. 실제 적용 이력 기록 권한이 있는 범위에서만 `--record-confirmed`를 추가한다. 기본 종료 절차는 KB usage 이력을 쓰지 않는다. 과거 연결/적용률을 추론하거나 대조 결과를 public projection에 넣지 않는다.

kb_selection은 검증된 저장 판단에 근거가 있고 문서가 실제 존재할 때 project/task/document별로 멱등 생성한다. 수동 보완 `kb-selection --project <프로젝트> --task <작업 ID> --document <문서>`도 저장된 판단이 필요하다. 기존 무연결 이벤트를 소급 변경하지 않는다.

### 실제 KB 대조 결과의 private 전송

실행한 대조는 private usage-data의 기기별 knowledge-reviews에 시도별 불변 이력으로 저장하고 task.knowledgeReviews로 집계·전송한다. [전송 계약](references/knowledge-reviews.md)에 따라 작업 identity, 당시 knowledgeDecisions/knowledge/evidence, digest, 대조 시각, 실행 상태, KB 반환 결과 또는 오류를 함께 보존한다. completed는 실행 완료이며 모든 문서의 matched를 뜻하지 않는다. failed/unavailable도 별도 시도로 남기고 이전 성공을 덮거나 현재 성공으로 재사용하지 않는다. 미실행은 이력 없음이다. 이전 로컬 결과에서 원본/시각을 추정해 backfill하지 않는다.

원본 digest가 달라지면 과거 원본의 결과로 표시한다. 같더라도 검사는 reviewedAt 당시 관측이므로 이후의 KB 문서/검색/적용 이력까지 일치한다고 주장하지 않는다. 공개 projection에는 대조 이력·snapshot·내부 경로를 넣지 않는다. 저장/전송 구현과 운영 전송 승인은 별개다. 수신 검증·화면 확인이 미완료면 완료로 보고하지 않는다.
