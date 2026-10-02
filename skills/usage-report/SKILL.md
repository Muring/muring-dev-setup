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

추적 설정이 있는 환경에서는 독립 작업 시작 시 `task-start --tool Codex|Claude --id <작업 ID> --project <대상 별칭>`으로 시작 경계와 고유 핸들을 기록하고, 종료 시 `task-finish --handle <그 핸들> --file <결과 JSON>`으로 이미 확인한 유형·상태·검증·재작업·KB 적용을 기록한다. 반환된 핸들은 해당 작업 맥락에 보관한다. 전역 current-task 파일을 만들거나 다른 터미널의 핸들을 재사용하지 않는다.

Codex는 `CODEX_SESSION_ID`·`CODEX_THREAD_ID`를 로컬 `session_meta.id`와 대조한다. Claude는 현재 세션에서 확인한 ID를 `--session-id`로, 또는 실제 훅 입력 파일을 `--hook-input`으로 전달하고 로그의 `sessionId`와 대조한다. 최신 파일·cwd만으로 현재 세션을 추측하지 않는다. 식별 불가면 `sessions: []`, 시작을 놓쳤으면 확인 가능한 시점부터만 기록한다. 별도 구간마다 새 핸들을 쓰며 작업 대상 프로젝트와 세션 출처 프로젝트는 구분한다. 상세 입력·과거 기록 조건은 지속 수집 안내를 따른다.

`task --file`은 경계를 모르는 결과나 근거가 있는 과거 기록에 사용한다. 시작·종료가 모두 확인되지 않은 연결은 집계에서 미상으로 남긴다. 세션 전체를 여러 작업에 일괄 연결하지 않는다. 데이터만 전용 worktree에 기록하며 일반 프로젝트 변경을 자동 커밋하지 않는다.

활성 일일 경로는 [Git 기반 발행 계약](references/git-publish.md)의 opt-in `publisher.mode=git-workflow`다. 하루 1회 수집·검증된 usage-data sync 성공 후 main workflow를 호출하고, 정확한 run/receipt를 검증해 접수·실행·DB 결과를 구분한다. 실패·미확인은 성공으로 바꾸지 않으며 실제 전송·예약 전환은 별도 승인 범위다. 이전 원본 DB 전달과 서버 정정은 기존 변경·검증 근거로 보존하며 현재 운영 대상이 아니다. Git 정정의 승인·감사 연결은 미완료 후속 범위다.
