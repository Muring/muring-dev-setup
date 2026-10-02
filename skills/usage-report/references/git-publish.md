# Git 기반 일일 집계 발행

2026-10-02 승인된 활성 경로는 하루 1회 수집 → 검증된 private `usage-data` sync → main workflow 호출 → aggregate DB 저장이다. Git은 원본·정확 중복 제거 근거를 보존한다. 원본 DB/서버 정정 확장은 운영 대상에서 제외하고 기존 코드를 보존한다.

## 최소 설정과 명령

기존 tracking.json에 아래 선택 설정을 추가하는 방식이다. 이 문서는 실제 설정·예약을 변경하지 않는다.

```json
{"publisher":{"mode":"git-workflow","repository":"Muring/muring-kb"}}
```

`delivery.mode=device-v1`과 동시 활성화할 수 없다. repository는 기존 guard가 검증한 origin과 같아야 하며 `git@github.com:owner/repo.git` 또는 자격정보 없는 `https://github.com/owner/repo.git`을 사용한다. main ref와 `publish-ai-usage.yml`은 고정한다. 기존 데이터 전용 commit/push·sidecar/이력 guard를 완화하지 않는다.

설정 후 `usage_tracker.py --config <tracking.json> scheduled` 또는 `run`은 KST09:00 기준 하루 한 번 수집한다. 수집 성공 marker를 먼저 보존해 sync/호출 실패로 같은 날 재수집하지 않는다. 기기가 꺼져 있었으면 다음 실행에서 보충한다. `sync` 명령도 성공 revision을 큐에 기록한 뒤 workflow를 호출한다.

- `publish-retry`: 수집 없이 필요한 sync 재시도와 미완료 run/receipt 확인. 실행 승인된 환경에서만 사용한다.
- `publish-status`: 저장된 발행 상태만 조회. Git·GitHub 호출 없음.
- 기존 `status`: publisher 상태도 함께 출력한다.

GitHub CLI `gh`가 실행 환경에 설치·인증돼 있어야 한다. fine-grained token은 대상 private repository의 Actions write(호출·run/artifact 조회)와 Contents read(revision 조상 비교)가 필요하다. Git sync 자격정보는 기존 방식이고 DB ingest key는 로컬에 추가하지 않는다. workflow의 `AI_USAGE_INGEST_KEY`, `AI_USAGE_INGEST_URL`, `AI_USAGE_EXPORTER_REF`는 KB 소유다. 토큰을 설정 JSON/인수/로그에 기록하지 않는다. [공식 dispatch 권한](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event), [run 조회](https://docs.github.com/en/rest/actions/workflow-runs), [artifact 조회](https://docs.github.com/en/rest/actions/artifacts).

## 요청·재시도와 완료 근거

논리 요청은 sync 성공 SHA40이며 시도마다 새 request_id(hex32)를 **호출 전** 내구 저장한다. inputs는 정확히 `requested_revision`과 `request_id`, workflow ref는 `main`이다. 현재 usage-data tip에 요청 SHA가 포함되는지는 KB workflow가 검증하고 실제 checkout HEAD를 sourceRevision으로 발행한다. 과거 요청 SHA로 되돌려 발행하지 않는다.

접수는 `accepted`, 아직 찾지 못한 실행은 `run_not_found`, 실행 중은 `running`이다. 다음 invocation에서 요청 ID가 들어간 run-name, workflow ID/path, repository, event=workflow_dispatch, head_branch=main을 확인한다. 발견 전에는 바로 중복 호출하지 않는다. 조회 오류는 미확인으로 남긴다. run이 10분 이상 발견되지 않으면 불확실한 이전 시도를 보존하고 조회 후 새 ID로 재시도한다. 한 invocation에서 sleep/poll loop를 돌리지 않는다. 실패·취소·잘못된 receipt는 다음 invocation에 새 시도로 재시도한다. 마지막 정상 DB 자료는 이 상태 때문에 0이나 성공으로 바뀌지 않는다.

성공 run만 `ai-usage-publish-receipt` artifact를 읽는다. 해당 run에 속하는 단일 작은 JSON만 허용하고 receipt.requestedSequence가 run_number와 같아야 한다. receipt.requestedRevision에 sync SHA가 포함되는지도 확인한다. 접수/성공 run만으로 DB 완료로 세지 않는다. artifact 소실·만료·형식 오류는 미확인이다. 실행 탐색은 최근 최대500건으로 제한하며 못 찾은 과거 run을 성공으로 간주하지 않는다.

상태는 `state/git-publish/requests/<syncSHA>.json`에 시도 이력과 검증된 receipt를 보존한다. `git-publish-daily.json`은 수집 경계, `git-publish-status.json`은 수집/sync/큐/실행 결과다. 삭제·자동 보존 축소·유료 전환은 없다.

## exporter와 ACK

`usage_publish.py`는 활성 manifest가 참조하는 hash 검증 shard만 대상으로 연도 필터 전 전역 identity 충돌을 확인한다. legacy aggregate의 계산 의미는 유지하며 같은 identity/같은 내용은 정확 중복 제거하고 다른 내용은 발행을 거부한다. superseded shard 파일을 현재 입력에 합치지 않는다.

`--send --receipt <새 JSON 경로>`는 기존 aggregate ACK `{accepted,sequence,sourceRevision}`를 strict 검증한 뒤에만 receipt를 생성한다. `--receipt` 없이 보내더라도 ACK를 검증한다. 기존 파일을 덮어쓰지 않으며 `--send` 없는 receipt 생성은 거부한다.

```text
{schema:1,state:"applied"|"already_applied"|"superseded",
 requestedSequence,requestedRevision,appliedSequence,appliedRevision}
```

true는 요청 sequence/revision과 같아야 `applied`. false의 같은 sequence·같은 revision은 `already_applied`, 더 큰 sequence는 `superseded`이며 그 요청 자체를 적용했다고 표시하지 않는다. 같은 sequence·다른 revision/더 낮은 sequence/구형 ACK는 오류다. payload·비밀값을 receipt artifact에 넣지 않는다. DB 단조 sequence guard는 receiver가 원자적으로 유지한다.

운영 전환에는 먼저 receiver ACK 호환, 이어서 고정 exporter revision/KB main workflow 및 로컬 설정 반영이 필요하다. 이 로컬 구현은 운영 전환 승인이 아니다. 기존 예약은 복구용으로 유지하며 별도 변경하지 않는다. Git 기반 정정·관리자 승인/감사 연결 및 v3 관계 정정은 이번 네 가지 변경에 포함하지 않는다.

검사는 `tests/usage-git-publish.py`(합성 GitHub/receipt·재시작·일일 경계·실제 receiver ACK fixture), 변경된 exporter 회귀와 필요한 sync 검사만 실행한다. receiver/KB workflow suite는 각 담당 결과를 재사용하고 전체·용량 검사를 반복하지 않는다.
