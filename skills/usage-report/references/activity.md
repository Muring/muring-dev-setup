# 선택 task.activity 기록

의미·기계 계약 소유는 muring-kb의 `contracts/ai-task-activity.schema.json`과 `scripts/ai_work_records.py`다. 배포용 계약 사본은 [JSON schema](ai-task-activity.schema.json)에 둔다. 추가 필드나 의미 변경은 canonical schema·synthetic fixture와 대조하고 그 저장소의 원본을 임의로 고치지 않는다. 런타임은 별도 KB checkout이나 추가 Python 패키지에 의존하지 않는다. 지원하지 않는 schema 키워드는 거부한다.

## 기록 경로와 호환

`task --file`, `task-finish --handle ... --file ...` 입력에 선택 activity를 넣는다. activity 자체 null은 무효이며 누락은 미수집이다. 같은 native task 업데이트에서 activity를 생략하면 기존 activity는 보존한다. 모든 object는 strict이며 필수 키를 생략하지 않는다. 문자열 공백만은 거부하고 일반 문자열 2000자·짧은 문자열 300자·배열 100개 한도를 따른다. 문자열 길이는 수신부와 같은 UTF-16 기준이며 정확한 제한은 schema와 canonical semantic 검증을 따른다. null은 미상, 빈 배열은 확인한 항목 없음이다.

선택 sidecar는 private usage-data의 `task-activities/<digest([project,id])>.json`에 `{ "version": 1, "project": "별칭", "id": "작업 ID", "activity": { ... } }`로 보관한다. 같은 내용은 멱등이며 native와 다르면 보류한다. task-presentations와 별개이며 개인 원본을 public 코드 저장소에 복사하지 않는다. 기존 task/presentation/토큰 합계/schema 1/usage-v1은 유지한다. 원본 기록을 추정·재번역·소급 채우지 않는다.

tracker/store/guard/index/원격 병합 후/publisher가 같은 strict·semantic 검증을 적용한다. 잘못된 파일명·없는 대상·충돌·symlink·잘못된 근거·효과·공개 승인은 오류다. stage된 내용과 작업 트리 모두 검사한다. 기존에 기록한 publicCase 상태를 바꾸려면 user_statement를 가리키는 review가 필요하다. 자동으로 최신 값을 선택하거나 원문을 합성하지 않는다. 실제 Git sync는 별도 승인 범위를 따른다.

## 기록 내용

- schemaVersion=1, category=work_execution/kb_maintenance/mixed/unknown. 프로젝트 이름·type으로 유추하지 않는다.
- purpose/actions/aiRole/humanRole/outcomes는 관측·명시적으로 확인한 내용만 요약한다. 작업/역할/결과/KB 사용을 기록했다면 evidence가 필요하다.
- evidence는 유일한 id, kind(user_statement/tool_result/artifact/comparison/session_record), private reference, nullable note다. evidenceRefs는 이 목록을 참조하며 중복·없는 근거를 거부한다. 결과별 및 pass/fail 검사별 근거는 필수다.
- verification은 checks와 unverified를 구별한다. check에 name/method/result/limitation/evidenceRefs를 둔다. 미실행은 not_run, 결과 미상은 unknown이다. 기존 task.verification은 변경하지 않는다.
- followUps의 pending/delegated/done/unknown과 knowledge의 reference/applied를 확인한 사실대로 구별한다.
- effects는 measured 또는 user_confirmed만 지원한다. 방법과 근거가 필수이며 measured는 유한 전후 숫자 둘 다 필요하다. user_confirmed는 사용자 진술 근거가 필요하고 값은 함께 null 또는 함께 숫자다. 0을 미상으로 바꾸지 않는다.

## 수행 날짜

timing에는 startedAt/endedAt/occurredAt/occurredOn/precision/labelDate/basis/evidenceRefs를 모두 둔다.

- timestamp: offset ISO datetime occurredAt과 근거가 필요하다. occurredOn은 null이며 시작·종료는 확인된 경우만 적는다. 시작은 종료보다 늦을 수 없다.
- date: 원본/사용자 근거로 확인한 YYYY-MM-DD occurredOn을 적는다. 세 timestamp는 전부 null이며 자정으로 변환하지 않는다.
- unknown: basis=unknown과 수행 날짜·시각 전부 null. ID에서 읽은 날짜만 있으면 labelDate={date,basis:"record_id"}에 두고 precision은 unknown을 유지한다.

작업 저장 시각·세션 연결로 날짜를 채우지 않는다. 프로젝트/기간별 활동 집계와 public projection 생성은 muring-kb 소유 도구가 수행하며, 이 전송기는 기존 토큰 합계를 재해석하지 않는다.

신규 `task-start`는 설정 timezone(기본 Asia/Seoul)의 실제 시작일을 task-runs에 수집한다. `task-finish`는 새 입력·기존 native·sidecar 모두 activity가 없을 때만 이 시작일을 date/source_record로 보존한다. 날짜가 바뀐 뒤 종료해도 시작일을 사용하며 역할·효과는 미상이다. activity를 직접 작성한다면 이 근거를 timing에 포함한다. 과거 핸들이나 명시적 unknown timing은 자동 보완하지 않는다.

2026-10-02 사용자 예외: 기존 53개 중 남은 날짜 미상 43개는 ID 날짜를 수행일로 사용하도록 명시 승인했다. 해당 보완만 date/user_confirmed로 저장하고 labelDate와 사용자 지시 근거를 함께 남긴다. 이는 실측 수행일 확인을 뜻하지 않으며 다른 과거 기록에 자동 확대하지 않는다. 신규 작업은 위 실제 시작일 수집을 따른다.

## 공개 경계

publicCase는 private task.activity 안에서만 전송한다. projection은 slug/title/problem/aiUse/result/verification/limitations/sourceUrl만 허용한다. 내부 식별자·경로·private 근거·reviewer 등은 공개 본문에 복사하지 않는다. sourceUrl은 공개 HTTPS이며 인증정보·query·fragment·private host를 금지한다. 자동 패턴 검사는 사람의 공개 검토를 대체하지 않는다. approved는 projection과 사용자 진술에 연결된 review 및 근거가 필요하다. 실제 공개 동작과 승인은 별개이며 모든 완료 작업을 우수 사례로 발행하지 않는다.

현재 작업에서는 수신부의 activity 지원 확인 및 운영 승인 전까지 `--send`, 예약 SHA 변경, 실제 데이터 sync/commit/push/배포를 실행하지 않는다. 사본 schema와 synthetic fixture 외 개인 자료를 코드 저장소에 넣지 않는다.

## 프로젝트 간 인계

선택 `activity.handoffs`의 누락/null은 미수집, []는 확인한 인계 없음이다. 기존 필수 키와 schemaVersion은 그대로다. 한 항목은 `{id,from,to,request,events}`이며 양 끝점은 `{project,taskId}`다. taskId가 미확인이면 null로 두고 후속에서도 헤더를 임의 변경하지 않는다. 수신 작업은 실제 만들어진 자기 task identity에 기록해 관리자 화면이 양쪽 source task로 연결할 수 있게 한다. 동일 ID/from/to/request는 재전송에도 보존하고 별도 요청·별도 수신처에는 새 인계 ID를 발급한다.

이벤트는 `{id,kind,reportedBy,at,occurredOn,precision,summary,evidenceRefs,result}`다. 사건마다 고유 ID를 사용하고 재기록은 같은 ID/내용을 보존한다. kind는 requested/dispatch_accepted/sent/received/started/blocked/completed/failed/cancelled이며 각 사건의 근거 최소 1개를 activity.evidence에 연결한다. timestamp는 at만, date는 occurredOn만, unknown은 둘 다 null이다. 기록 저장 시각으로 사건 시각을 채우지 않는다.

- requested는 sender/user, dispatch_accepted는 transport가 보고한다. input_accepted만으로 sent/received를 만들지 않는다.
- received/started/blocked/completed/failed는 recipient/user 근거가 필요하다. 상대 결과를 전달받아 옮겨도 recipient 보고로 기록한다. user 보고는 user_statement 근거가 필수다. transport로 취소를 판정하지 않는다.
- completed/failed에만 result `{summary,artifacts,verification}`를 둔다. 다른 사건은 null이다. 검사 미상은 verification=null이며 미실행 운영/UI 검사를 통과라고 쓰지 않는다.
- 이 작업의 project/id가 from 또는 to와 일치해야 한다. taskId=null이면 project 일치만 확인한다.
- native/sidecar를 업데이트할 때 기존 헤더·이벤트·근거는 보존한다. 같은 ID의 다른 헤더/이벤트/서로 다른 종료 결과는 저장 원본을 합성하지 않고 sync/publisher를 보류한다. 여러 작업에서 증거 ID가 달라도 실제 근거 내용과 사건이 같으면 동일 사건으로 검증한다. 타임라인 병합·충돌 원문 표시는 KB 집계/수신 UI 소유다.

발신·수신·결과를 원본 task 또는 private activity sidecar로 저장하고 기존 presentation을 유지한다. 인계 자료와 근거를 public projection에 추가하지 않는다. 실제 전송/게시 승인과 기록은 별개다.

## KB 판단과 종료 대조

선택 `activity.knowledgeDecisions`는 array|null이다. 기존 필수 키와 knowledge를 보존한다. 항목의 정확한 키는 `{id,document,selection,searchRefs,decision,reason,plannedUse,verification,evidenceRefs}`이며 document는 정규 KB 상대 경로다. decision id와 document는 각각 유일해야 한다.

- selection은 search/direct. search는 실제 32자리 hex searchId를 1개 이상, direct는 빈 searchRefs를 사용한다.
- decision은 applied/reference_only/not_applicable/deferred/unknown. reason은 필수이며 unknown 외 판단에는 activity.evidence를 참조하는 근거가 필요하다.
- plannedUse는 구체적인 예정/실제 적용 내용 또는 null이다. verification은 `{method,result,note,evidenceRefs}` 또는 null이다. result는 pass/fail/not_run/unknown이며 applied는 plannedUse와 pass/fail 및 검사 근거가 필수다. 실패한 적용을 미적용이나 성공으로 바꾸지 않는다.
- legacy knowledge의 같은 문서 applied/reference와 모순이면 저장을 거부한다. native/sidecar와 기기 간 상충 판단은 guard/sync/publisher에서 보류하며 자동 승자를 만들지 않는다.

```sh
python3 <scripts>/usage_tracker.py kb-search --handle <현재 핸들> --keyword '관련 주제'
python3 <scripts>/usage_tracker.py task-finish --handle <현재 핸들> --file <결과 JSON>
python3 <scripts>/usage_tracker.py knowledge-review --handle <현재 핸들>
```

종료 대조는 저장된 task/sidecar와 로컬 검색 이벤트·KB usage/events를 KB knowledge-review CLI에서 비교한다. 실제 대조 시도는 원본 판단·근거 snapshot과 함께 private task.knowledgeReviews로 저장·전송하며 activity와 public projection은 변경하지 않는다. 상세 저장·수신 계약은 [대조 결과 전송](knowledge-reviews.md)을 따른다. matched/missing_application_record/not_applied/decision_unknown/uncollected/broken_search_link/search_unavailable/not_recordable_document/document_missing/application_decision_conflict/task_conflict를 구별한다. CLI 미설치/의존성·입력 오류는 unavailable/failed로 표시하며 저장된 작업 결과를 버리지 않는다. `--record-confirmed`는 별도 허용 범위에서만 실제 KB 적용 이력을 멱등 보완한다.

선택 이벤트는 근거 있는 저장 판단에서만 생성하며 project/task/document별 같은 최초 관측 시각을 보존한다. 이 시각은 문서를 읽은 시각이나 적용 시각의 추정치가 아니다. 원문 검색어·snippet·활동 근거 본문은 이벤트에 넣지 않는다. 과거 무연결 검색은 미상으로 유지한다. KB CLI의 telemetry는 기본 `~/.config/ai-workflow/tracking.json`을 사용하므로 별도 tracker config의 repo/state가 다르면 kb-search는 명시적으로 중단한다.

기존에 저장한 같은 문서의 판단·근거를 바꾸거나 삭제하는 업데이트는 충돌로 보류한다. 후속 적용은 새 작업/검증 근거로 기록하고, 잘못된 원본의 정정은 근거를 확인한 명시적 조정 절차로 처리한다. tracker가 자동 최신 판단을 선택하지 않는다.
