# Private knowledge-review delivery v1

인계: kb-review-delivery-20261002-dev-bootstrap. 기존 KB contracts/README.md와 scripts/kb_knowledge.py의 상태 의미는 변경하지 않는다. 새 필드는 private task의 선택 `knowledgeReviews` 배열이며 activity/public projection은 불변이다.

## 전송 계약

`task.knowledgeReviews?: KnowledgeReview[]` (최대 1000개, 누락=수집된 대조 이력 없음; null 불허). 각 객체는 아래 키만 허용하며 모두 필수다.

```ts
type KnowledgeReview = {
  schemaVersion: 1;
  id: string; // 32 lowercase hex, actual attempt identity; immutable
  project: string;
  taskId: string;
  reviewedAt: string; // actual offset ISO timestamp of this reconciliation attempt
  status: 'completed' | 'failed' | 'unavailable';
  source: {
    knowledgeDecisionsPresent: boolean;
    knowledgeDecisions: KnowledgeDecision[] | null;
    knowledge: LegacyKnowledge[] | null;
    evidence: ActivityEvidence[];
  };
  sourceDigest: string; // 64 lowercase hex SHA256, described below
  result: {
    schemaVersion: 1;
    visibility: 'private';
    rows: KnowledgeReviewRow[];
    recordingRequested: boolean;
    inferredApplications: 0;
  } | null;
  error: string | null;
};
```

source는 대조에 전달한 activity의 knowledgeDecisions/knowledge/evidence 사본이다. activity 또는 선택 키가 없으면 presence=false, knowledgeDecisions=null. 명시 null이면 presence=true/null, []면 true/[]. knowledge 누락은 null, evidence 누락은 []다. 그 외 기존 activity 스키마/의미 검증을 그대로 적용한다. 원래 문서·판단·근거는 현재 task.activity와 과거 source 양쪽에 보존한다.

sourceDigest = SHA256(UTF-8 canonical JSON of `{project, id: taskId, source}`). canonical JSON은 재귀적으로 객체 키를 사전순 정렬하고 배열 순서를 보존하며 공백 없이 출력한다. Unicode는 그대로 출력한다(ensure_ascii=False). source에는 실수 필드가 없으며 문자열 Unicode 정규화를 하지 않는다. 수신기는 digest 무결성·task identity를 검증하고 현재 activity에서 같은 source를 구성해 원본 일치 여부를 확인한다. 원본이 바뀌었어도 과거 결과는 버리지 않으며 **과거 원본의 대조 결과**로만 표시한다.

completed는 CLI 실행·결과 검증 완료를 뜻하며 모든 문서의 matched를 뜻하지 않는다. completed일 때 result 필수/error=null. failed/unavailable이면 result=null/error는 비어 있지 않은 최대2000자 문자열. 이전 성공을 후속 오류로 덮어쓰거나 오류 후 이전 성공만 현재 결과로 선택하지 않는다. CLI 미설치=unavailable, 실행·검증 실패=failed. 미실행은 배열 누락으로 나타내며 가짜 review를 만들지 않는다.

## result.rows (KB 반환 그대로)

rows는 최대 100개다. 각 row의 공통 필수 키는 `{project, task, document, state}`다. project/task는 review의 identity와 같아야 한다.

- document=null: state는 uncollected 또는 task_conflict. 다른 키 없음.
- document=원본 결정의 상대 경로: `{decision,reason,searchLink}`도 필수. decision/reason은 해당 source 결정과 동일하다. searchLink는 direct/linked/broken_search_link/search_unavailable.
- state: matched, missing_application_record, not_applied, decision_unknown, uncollected, broken_search_link, search_unavailable, not_recordable_document, document_missing, application_decision_conflict, task_conflict, recorded.
- 선택 detail:string은 not_recordable_document에만 허용.
- 선택 applicationEvent:string은 recordingRequested=true이고 state=recorded 또는 matched인 경우에만 허용. private 경로이며 공개 금지. recorded이면 필수.
- 실제 source 판단과 row 상태의 모순, 중복/누락 문서, 다른 identity, 미등록 키는 거부한다. uncollected는 source가 누락/null인 경우다. source=[]이면 rows=[]다. task_conflict는 단일 null 문서 row로 보존한다.

## 과거 결과와 공개 경계

모든 결과는 reviewedAt **당시 관측**이다. 원본 digest가 같아도 KB 이력·문서·검색 이벤트가 이후 바뀔 수 있으므로 현재 정상 일치라고 보증하지 않는다. 수신 UI는 대조 시각, 당시 상태, 원본 불일치/오래된 관측임을 표시하고 자동 TTL·적용률·미사용 판정을 만들지 않는다. 최신 시각을 자동 승자로 삼거나 서로 다른 시도의 결과를 합성하지 않는다. 이력은 시간순 정렬할 수 있지만 오류/미상/예전 결과를 숨기지 않는다.

private task.knowledgeReviews 외 공개 projection/공개 응답에는 추가하지 않는다. publicCase 승인 여부와 무관하게 이력·source·근거·내부 경로는 private이다. 기존 activity 없는 legacy task와 기존 totals/verification/presentation을 변경하지 않는다.

## 저장·검증

private usage-data의 `devices/<device>/knowledge-reviews/<id>.json`에 시도별 불변 객체를 저장한다. 기존 로컬 `state/knowledge-reviews/<handle>.json`은 호환 유지한다. 이전 로컬 결과만으로 원본 source/시각을 추정하여 과거 이력을 backfill하지 않는다.

store는 원본/sidecar 병합 후 task identity로 연결하고 동일 id/내용만 중복 제거한다. 같은 id의 다른 내용, 없는 대상, task 충돌, 형식 오류는 guard/index/병합 후 및 publisher에서 실패한다. 이전 review의 삭제/수정은 자동 sync로 허용하지 않는다. 시도 추가만 허용한다. 전체 이력 1000개 초과는 조용히 자르지 않고 실패한다.

공유 합성 전송 fixture: `tests/fixtures/knowledge-reviews.json` (현재 37개). 각 case의 valid는 review 자체의 전송 계약 유효성이다. 현재 task.activity와 source가 다른 stale_source_preserved는 valid=true이며 최신 일치로 승격하지 않는다.
