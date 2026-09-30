# MuRing Dev Setup

Windows PC에서 **WSL2 + Ubuntu 개발환경을 안내하며 설치하는 마법사**입니다.
개인 PC 재설치를 위한 MuRing 구성을 기본 제공하고, 공통 개발환경 구성도 선택할 수 있습니다.
업무 프로젝트, 프로젝트의 비밀값, DB 설정은 설치하지 않습니다.

기존 **Dev Bootstrap**의 새 이름입니다. 0.1.9부터 새 이름을 사용하며, 기존 0.1.8 릴리스는 유지합니다.
새 빌드의 파일명은 `MuRingDevSetup-<버전>-x64.exe`이며, 설치 경로와 기존 설정은 그대로 사용합니다.
GitHub 저장소는 `Muring/muring-dev-setup`으로 개명했습니다. [개명 전환 기록](docs/RENAMING.md)에서 호환성 유지 범위를 확인할 수 있습니다.

## 앱으로 시작하기

1. [MuRingDevSetup-0.1.14-x64.exe 다운로드](https://github.com/Muring/muring-dev-setup/releases/download/MuRingDevSetup-0.1.14-x64.exe/MuRingDevSetup-0.1.14-x64.exe)를 눌러 EXE를 받습니다. **Git clone은 필요 없습니다.**
2. 다운로드한 `MuRingDevSetup-0.1.14-x64.exe`를 **Windows 로컬 폴더에서 실행**합니다. 서명되지 않은 파일이라 처음 한 번은 SmartScreen 창이 뜹니다. **추가 정보 → 실행**을 누르세요. 앱이 시작되면 다운로드 표시를 스스로 지워 다음 실행부터는 묻지 않습니다. 그래도 계속 뜨면 파일 속성에서 **차단 해제**를 체크하세요.
3. **환경 확인**을 누릅니다. WSL, 기존 Ubuntu, 드라이브 여유 공간과 Orca 상태를 검사합니다.
4. WSL이 없으면 **WSL 준비**를 누릅니다. 이 단계에서만 Windows 관리자 권한(UAC) 창이 한 번 뜹니다. WSL 기능과 Store판 WSL 패키지(`wsl --version`으로 확인)가 모두 준비돼야 **준비됨**으로 표시되고 다음 단계가 열립니다. 이후 단계의 wsl.exe 호출이 스스로 관리자 권한을 요청하지 않게 하기 위해서입니다. 다른 버튼은 관리자 권한을 쓰지 않으며, Orca 설치 창만 Orca 설치 파일 자체의 권한 요청이 있습니다.
5. 재부팅이 필요하면 작업을 저장하고 재부팅한 다음 같은 앱을 다시 엽니다.
6. Ubuntu 저장 위치와 Linux 사용자명을 선택하고 **Ubuntu 설치**를 누릅니다. 기존 Ubuntu라면 현재 위치와 개발 계정을 사용합니다.
7. **설치 구성**에서 원하는 항목을 선택합니다. `Recommended`는 권장 표시이며 선택을 해제할 수 있습니다.
8. **변경 내용 확인**에서 설치 대상, GitHub 커맨드·스킬의 커밋과 변경 파일을 확인하고 설치를 시작합니다.
9. 별도 Ubuntu 실행 창의 안내를 따릅니다. 기존 계정의 sudo 비밀번호가 필요하면 그 창에 입력합니다.
10. 앱의 **로그인 · 연동**에서 GitHub·Claude·Codex 로그인과 KB·Orca 연결을 마칩니다.
11. 선택한 항목의 설치와 계정 연결을 마친 뒤 **설치 완료 확인**을 누릅니다.

PC 상태의 WSL 버튼은 가운데, Orca 버튼은 오른쪽 상태 칸 아래에 표시합니다.
준비된 WSL과 설치된 Orca의 설치 버튼은 비활성화됩니다. **환경 확인 / 새로고침**으로 상태를 다시 확인할 수 있습니다.
WSL 최신 버전 비교 기능은 없으며, 필요할 때 Windows PowerShell에서 `wsl --update`로 업데이트합니다.

제목·단계 메뉴·이전/다음 버튼은 고정되고 본문만 스크롤됩니다.
오른쪽 진행 상황 패널은 각 단계에서 실행한 마지막 작업의 상태·진행 과정을 보여 주며, 다른 단계로 가면 그 단계의 기록으로 바뀌고 돌아오면 다시 보입니다. 접으면 상태 점과 경과 시간만 남고, 설치 진행 단계에서는 설치 진행 기록도 이 패널에 표시됩니다.
환경 확인 전에는 설치 구성을 열 수 없고, 구성 검토 전에는 설치를 시작할 수 없습니다.
설치 실패·중지 상태에서는 로그인·연동 단계가 잠깁니다. KB 인증·Orca 연결 대기는 그 화면에서 해결합니다.
선택한 설치와 계정 연결을 완료해야 완료 화면이 열립니다. 대상 계정이나 구성을 바꾸면 다시 확인해야 합니다.
**커맨드 · 스킬 업데이트**는 별도 유지 관리 기능이며 Ubuntu 환경 확인 후 전체 재설치 없이 사용할 수 있습니다.

**사용자 PC에 Git, Node, Python을 미리 설치하거나 이 저장소를 clone할 필요가 없습니다.**
실행 파일에는 앱 런타임과 설치 스크립트가 들어 있습니다. 커맨드·스킬은 설치 시 GitHub에서 별도로 받습니다. 다운로드에는 인터넷이 필요합니다.
[릴리스 페이지](https://github.com/Muring/muring-dev-setup/releases/tag/MuRingDevSetup-0.1.14-x64.exe)에서 변경 내용과
[SHA-256 파일](https://github.com/Muring/muring-dev-setup/releases/download/MuRingDevSetup-0.1.14-x64.exe/SHA256SUMS.txt)도 확인할 수 있습니다.
현재 버전은 서명되지 않은 **초기 검증판(Pre-release)**입니다. 신규 Windows 전체 설치 검증은 아직 남아 있습니다.
GitHub의 `Source code (zip/tar.gz)`는 개발용 소스이며, 설치할 때는 `.exe` 파일을 받으세요.

첫 버전의 지원 대상은 **Windows 11 x64 + WSL2 + Ubuntu**입니다.
기존 WSL1 배포판의 자동 전환, 기존 Ubuntu의 이동·삭제, 다른 Linux 배포판은 지원하지 않습니다.
Windows 저장 위치는 Ubuntu 가상 디스크의 위치이며, Ubuntu 내부 홈 경로는 `/home/<사용자>`입니다.
새 Ubuntu 계정에는 개발용 WSL을 위한 비밀번호 없는 sudo 권한이 부여됩니다.

## 작업 진행 상황과 선택 목록

시간이 걸리는 작업은 제목 아래의 고정된 **작업 진행 상황** 패널에서 확인합니다.
환경 확인, WSL·Ubuntu 준비, 개발환경 설치·재시도, 계정 로그인, 커맨드·스킬 확인·적용, Orca 다운로드, 재시작 모두 같은 패널을 사용합니다.

- 현재 작업과 경과 시간, **진행 과정**을 펼친 단계 이력을 표시합니다.
- Windows 검사와 Ubuntu 인증·도구 검사는 완료한 검사 항목 수를 표시합니다.
- Orca 다운로드는 실제 받은 MB와 전체 크기, 퍼센트를 표시하고 이후 체크섬 검증·설치 창 실행을 구분합니다.
- 커맨드·스킬 업데이트는 파일 다운로드 수, 검증, 백업, 연결 적용·복구 과정을 표시합니다.
- WSL 설치나 로그인 창처럼 정확한 진행률을 제공하지 않는 외부 작업은 현재 과정과 경과 시간을 표시합니다. 예상 퍼센트나 남은 시간을 임의로 계산하지 않습니다.
- 로그인·외부 설치 창·재부팅 대기, 실패, 취소는 완료와 구분합니다. 별도 창의 입력 요청은 해당 창에서 진행하세요.
- 가장 최근 작업 과정은 `%LOCALAPPDATA%\dev-bootstrap\last-operation.json`에 남깁니다. 인증 명령의 원문 출력이나 토큰은 진행 패널에 수집하지 않습니다.

진행 이력과 설치 로그는 배경·테두리가 있는 독립 박스로 표시합니다. 본문·로그·드롭다운·메뉴에는 mublog 관리 화면과 같은 얇고 둥근 스크롤바를 적용했습니다.

배포판·저장 위치 드롭다운은 펼친 목록도 앱 스타일로 표시합니다. 방향키·Home/End로 이동하고 Enter로 선택합니다. Escape·Tab·목록 밖 클릭으로 닫을 수 있습니다.

## 설치 후와 다음 버전 사용

- 첫 설치는 환경 확인 → 설치 구성 → 변경 내용 확인 → 설치 → 로그인·연동 순서로 진행합니다.
- 설치 도중 재부팅하면 같은 EXE를 다시 실행하고 환경 확인 후 계속합니다.
- 설치가 끝나면 새 Ubuntu 터미널에서 선택한 도구의 버전을 확인합니다. KB 등록 후에는 새 Codex 세션을 시작합니다.
- 실패하면 **로그 폴더 열기**에서 해당 실행의 `events.jsonl`과 `events.log`를 확인하고 미완료 단계를 재시도합니다.
- 다음 버전은 [전체 릴리스 목록](https://github.com/Muring/muring-dev-setup/releases)에서 새 EXE를 받아 실행합니다.
  자동 업데이트는 없습니다. 같은 Windows 계정의 선택 기록을 읽고 실제 상태를 다시 검사합니다.
- 다음 버전 설치도 변경 내용 확인 화면을 거칩니다. 기존 Ubuntu나 개발환경을 먼저 삭제할 필요가 없습니다.
- 개발자가 새 버전을 배포하는 절차는 [배포 가이드](docs/RELEASING.md)를 따릅니다.

## 커맨드·스킬만 업데이트하기

**기존 0.1.0 사용자는 0.1.14 EXE를 한 번 새로 받으세요.** 이후 커맨드·스킬 내용 변경에는 EXE 재다운로드가 필요 없습니다.

1. Windows에서 앱을 열고 대상 Ubuntu와 Linux 계정을 확인합니다.
2. **설치 구성**에서 Claude 스킬·Claude 커맨드·Codex 공용 스킬 중 사용할 항목을 선택합니다.
3. 왼쪽 **커맨드 · 스킬 업데이트** → **업데이트 확인**을 누릅니다.
4. GitHub `main`의 커밋, 명령 목록과 변경 파일을 확인한 뒤 **확인한 버전 적용**을 누릅니다.
5. 새 Claude·Codex 세션에서 `/commit`, `$commit`처럼 호출합니다.

이 작업은 sudo나 개발 도구 재설치 없이 실행됩니다. 확인 이후 main이 바뀌어도 확인한 커밋만 적용합니다.
이미 이 설치기로 등록한 대상들은 같은 콘텐츠 버전을 함께 사용합니다. 선택 해제는 기존 연결의 삭제를 뜻하지 않습니다.
최신 파일을 자동 적용하거나 앱 시작 때마다 다운로드하지 않습니다.

- 공용 원본: `skills/<name>/SKILL.md` 일반 파일. `commands/<name>.md`는 해당 원본을 가리키는 상대 링크입니다.
- Claude 커맨드: `~/.claude/commands`; Claude 스킬: `~/.claude/skills/<name>`.
- Codex 스킬: `${CODEX_HOME:-~/.codex}/skills/<name>`. 별도 경로를 사용한다면 대상 Ubuntu의 실행 환경에 `CODEX_HOME`을 설정하세요. 저장한 경로는 다음 업데이트에서도 사용합니다.
- 다운로드: `~/.local/share/dev-bootstrap/content/releases/<커밋>`; 적용 중인 원본: `content/current`.
- 상태: `content/state.json`; 이전 콘텐츠와 연결 백업: `content/backups/<시간>/`.
- 기존 0.1.0 앱의 runtime을 가리키는 알려진 링크는 백업 후 전환합니다.
  다른 checkout의 링크나 직접 만든 파일·디렉터리는 덮어쓰지 않고 중단합니다. 표시된 경로의 내용을 확인하고 직접 보관·이동한 뒤 재시도하세요.
- 다운로드·해시 검증 실패 시 기존 설치를 유지합니다. 적용 중 실패는 연결을 복구하며, 강제 종료 후에는 다음 적용 때 복구합니다.
- 네트워크 또는 GitHub API 호출 한도 오류가 나면 잠시 후 다시 확인하세요. 현재 설치된 커맨드·스킬은 계속 사용할 수 있습니다.
- 업데이트 기록: Windows `%LOCALAPPDATA%\dev-bootstrap\content-<시간>\result.json`.

콘텐츠 수정자는 원본을 수정하고 검증한 뒤 GitHub에 commit/push하면 됩니다. 설치 UI·설치 코드·항목 구조 변경은 새 EXE 릴리스가 필요합니다.

Ubuntu CLI로 콘텐츠만 적용하려면 최신 checkout에서 일반 계정으로 실행합니다:

```bash
python3 linux/content.py preview
# 위 출력에서 확인한 40자리 commit 값을 사용
python3 linux/content.py apply --commit <확인한-40자리-SHA> --group claude-commands --group claude-skill --group codex-skills
```

비대화형 전체 설치 JSON에서 콘텐츠 항목을 선택했다면 `"contentCommit": "<확인한-40자리-SHA>"`를 넣어야 합니다.
대화형 설치와 앱은 변경 확인 단계에서 값을 채웁니다. 콘텐츠를 선택하지 않은 기존 구성에는 필요 없습니다.

## AI 작업 명령

Claude에서는 `/명령`, Codex에서는 `$명령`으로 같은 원본을 호출합니다. 위 커맨드·스킬 업데이트로 함께 설치됩니다.

| 명령 | 역할 |
|---|---|
| `code-audit` | 프로젝트 **전체 코드**를 11개 관점에서 점검. 변경분 검사로 축소하지 않음 |
| `verify-changes` | `.agent-checks.json`에 따라 변경 후 기존 회귀 검사 실행. 요약과 상세 로그 경로 반환 |
| `usage-report` | 로컬 Codex·Claude 집계, 여러 기기 증분 수집·데이터 전용 동기화·승인된 HTML. 과금/한도 조회와 구분 |
| `wait-deploy` | 기존 GitHub 배포·CI 상태를 backoff로 대기. push나 배포 실행 없음 |
| `session-brief` | 결정·검증·남은 일과 worktree 상태를 짧게 인계 |
| `shopify-pdp` | PDP 제작 도구. 변경 섹션 검증과 짧은 결과 출력 지원 |

스크립트는 각 `skills/<명령>/scripts/`에 있고 스킬 경로를 기준으로 실행합니다. `verify-changes`는 같은 콘텐츠 버전의 `session-brief` 조회 모듈을 사용합니다. 실행기는 Python 3.10+와 Git이 있는 Linux/WSL 환경용이며 배포 대기는 인증된 `gh`, PDP 브라우저 검증은 기존 `pdp setup` 런타임이 필요합니다.

```bash
# checkout에서 실행하는 예. 명령 파일 위치와 대상 프로젝트를 구분합니다.
python3 skills/usage-report/scripts/usage_report.py --week --by project,tool,session --json
python3 skills/session-brief/scripts/session_brief.py --repo /path/to/project --json
python3 skills/verify-changes/scripts/verify_changes.py --repo /path/to/project --base HEAD --run --json
# 대상 GitHub 저장소에서 실행하거나 --repo owner/repo --sha <전체 SHA> 지정
python3 /path/to/dev-bootstrap/skills/wait-deploy/scripts/wait_deploy.py --context Vercel --json
```

사용량 조회의 기본 기간은 KST 월요일부터 현재까지이며 `--since`, `--until`(종료 제외), `--timezone`으로 조정합니다. `--home`을 반복해 WSL/Windows 로그를 함께 읽거나 `~/.config/ai-workflow/usage.json`에 `{"homes":["/home/me","/mnt/c/Users/Me"]}`를 저장합니다. 대화 원문·인증 파일을 출력하거나 외부로 전송하지 않습니다. 누락된 로그와 누적값 기준 누락은 warnings로 알리며 청구 전체 사용량을 보장하지 않습니다.

최근 7일의 Codex만 분석하려면 `--tool codex --days 7 --diagnostics --by project,model,day,session --json`을 사용합니다. 진단은 입력 크기, 큰 도구 출력의 문자 수, 잘림 표시, 동일 호출 반복을 집계하며 명령·출력 원문은 보고서에 포함하지 않습니다. 반복 호출에는 필요한 대기·재검증도 포함되므로 자동으로 낭비나 절감률로 해석하지 않습니다.

`verify-changes`는 기본적으로 실행 계획만 보여주고 `--run`에서 설정의 argv를 실행합니다. `--all`도 등록된 회귀 검사 전체를 뜻하며 전체 코드 감사가 아닙니다. 기존 통과 결과를 캐시하지 않습니다. UI 검증은 대상 URL·worktree·인증 상태를 맞추고 기존 Orca 탭을 우선 사용합니다.

PDP는 `pdp verify --project DIR --sections 2,5 --summary`로 부분 반복 검증을 할 수 있습니다. 부분 결과는 별도 경로에 기록하며 최종 전달 전에는 `--sections` 없이 전체 검증합니다. `pdp audit --project DIR --summary`는 전체 구조 검사입니다. 로컬 PDP 도구를 업데이트된 공용 원본으로 옮길 때는 기존 실제 디렉터리를 보관한 뒤 링크를 바꾸고, 서로 다른 원본을 덮어쓰지 않습니다.

## 기본 구성과 Recommended

| 항목 | MuRing 구성 | 공통 구성 |
|---|---|---|
| Git·Python·curl·빌드 도구 | Required | Required |
| fnm·Node 22.23.2·Corepack | 선택됨 · Recommended | 선택됨 · Recommended |
| GitHub CLI | 선택됨 · Recommended | 선택됨 · Recommended |
| Claude Code·Codex | 각각 선택됨 · Recommended | 선택 해제 |
| zsh·로그인 셸 변경 | 선택됨 · Recommended | 선택 해제 |
| 프롬프트·zsh 플러그인 | 선택됨 · zsh 사용 시 Recommended | 선택 해제 |
| 기존 `.zshrc` 전체 교체 | 선택 해제 | 선택 해제 |
| Git 작성자·기본 브랜치·Windows GCM | 각각 선택 해제 | 각각 선택 해제 |
| 시간대 변경 | Asia/Seoul 선택됨 | 기존 값 유지 |
| Claude 개인 설정·스킬·커맨드 | 각각 선택됨 | 선택 해제 |
| Codex 공용 스킬 | 선택됨 · Recommended | 선택 해제 |
| Claude 권한 경고 생략 설정 | 선택 해제 | 선택 해제 |
| 개인 KB·Orca 스킬 | 각각 선택됨 · Recommended | 선택 해제 |
| Orca Codex 실행 설정 | 선택됨 · Recommended | 선택 해제 |
| Orca 1.4.202/1.4.215 패치 | 선택 해제 | 선택 해제 |
| Orca 패치 누락 감시 | 선택 해제 | 선택 해제 |

도구를 선택하면 필요한 의존성도 함께 선택합니다. 의존성을 해제하면 관련 도구도 함께 해제하며,
화면에 함께 변경된 항목을 표시합니다. 선택하지 않은 항목은 설치 실패로 집계하지 않습니다.
Orca 패치는 검증된 파일이 있을 때만 선택 가능합니다.

### 기존 설정은 어떻게 처리하나요?

- 기본 동작은 **기존 `.zshrc` 보존**입니다. 필요한 초기화만 관리 블록으로 연결합니다.
- 공통 실행 경로와 fnm 초기화는 `~/.config/dev-bootstrap/env.sh`에 저장합니다.
- Bash의 `.bashrc`와 실제 사용되는 로그인 설정에도 초기화를 연결합니다.
- zsh를 선택하면 `.zshrc`에 연결을 추가합니다. `.zshrc.local`은 마지막에 읽습니다.
- 프롬프트·단축키·플러그인을 선택하면 기존 사용자 파일을 지우지 않고 관리 설정을 읽습니다.
  이 관리 설정이 기존 프롬프트·단축키의 동작을 바꿀 수 있으며, `.zshrc.local`에서 조정할 수 있습니다.
- **전체 교체를 직접 선택한 경우에만** 기존 `.zshrc`를 교체합니다.
- 변경하는 사용자 설정 파일은 같은 폴더에 `.bak.<시간>`으로 백업합니다.
- 같은 구성으로 반복 실행해도 관리 블록이나 백업이 불필요하게 늘어나지 않습니다.
- Claude 설정 파일이 이미 있으면 개인 기본 설정으로 덮어쓰지 않습니다.
  별도로 선택한 권한 경고 생략 설정은 백업 후 해당 키만 변경합니다.
- 기존 Claude 스킬·커맨드 경로가 일반 디렉터리라면 보존하고 충돌을 보고합니다.

앱 설치 자산은 Ubuntu의 `~/.local/share/dev-bootstrap/runtime`에 복사합니다.
커맨드·스킬은 별도의 `~/.local/share/dev-bootstrap/content`에 저장하므로 EXE를 옮겨도 유지됩니다.
설치 스크립트는 EXE에 포함된 버전을 사용하고, 콘텐츠만 GitHub에서 가져옵니다.

## 로그인과 수동 작업

### GitHub / 개인 KB

앱의 GitHub 로그인 버튼을 누르면 대상 Ubuntu 터미널에서 로그인을 진행합니다.
MuRing 기본 KB는 `https://github.com/Muring/muring-kb.git`이며 해당 비공개 저장소 읽기 권한이 필요합니다.
공통 구성에서도 KB를 선택하고 다른 GitHub HTTPS 저장소와 Ubuntu 설치 경로를 지정할 수 있습니다.
대상 KB는 `START-HERE.md`, `scripts/setup.py`, `scripts/kb.py`를 제공하는 호환 저장소여야 합니다.

인증 후 **KB 연결 재시도**를 누릅니다. 기존 KB checkout은 자동 pull하지 않습니다.
연결은 Codex 전역 지침(`~/.codex/AGENTS.md`)에 KB를 등록하고 Claude Code 전역 지침(`~/.claude/CLAUDE.md`)이 그 파일을 가져오도록 설정합니다. 끝나면 각 도구의 새 세션을 시작하세요.

### Claude / Codex

앱의 로그인 버튼으로 각각 로그인합니다. 앱은 계정 토큰이나 비밀번호를 수집·저장하지 않습니다.
CLI 자체가 관리하는 인증 상태만 검사합니다. 인증 상태는 도구 설치와 별도로 검사합니다. 앱의 완료 화면은 선택한 계정 연결까지 마친 뒤 열립니다. 앱을 닫았다가 환경 확인 후 이어서 진행할 수 있습니다.

### Orca

앱의 **환경 확인** 또는 **로그인 · 연동** 화면에서 **Orca 다운로드 · 설치**를 누르면
[공식 Orca 배포](https://www.onorca.dev/docs/install)의 최신 안정판 Windows 설치 파일을 받아 실행합니다.
GitHub 배포 메타데이터의 SHA-256과 파일 크기를 검증하며, 다운로드나 검증 실패 시 실행하지 않습니다.
이미 설치되어 있으면 덮어설치하지 않습니다. 기존 Orca의 업데이트는 Orca 앱에서 진행하세요.

1. **Orca 다운로드 · 설치**를 누르고 열린 공식 설치 창에서 설치를 마칩니다. 로그인은 Orca 앱에서 진행합니다.
2. Orca에서 설치 대상 Ubuntu의 WSL 터미널을 한 번 엽니다.
3. 설치 마법사에서 **Orca 설치 상태 확인** 후 **Orca 스킬 연결**을 누릅니다.
4. **Orca Codex 실행 설정**을 선택했다면 Orca를 완전히 종료하고 **Codex 실행 설정 적용·확인**을 누릅니다. 새로 여는 Codex에 `--no-daemon`을 적용해 공유 데몬의 다른 워크트리 환경을 물려받는 문제를 피합니다. 실행 중인 세션을 강제 종료하지 않으며, 이미 적용된 설정은 실행 중에도 확인만 합니다.
5. 패치를 선택했다면 스킬 연결 후 Orca를 완전히 종료하고 **패치 적용**을 누릅니다.

설치 파일과 검증 정보는 `%LOCALAPPDATA%\dev-bootstrap\downloads`에 저장합니다.
설치 버튼은 자동 무인 설치가 아니라 공식 설치 창을 여는 동작입니다.

Codex 실행 설정은 `codex --help`에서 `--no-daemon` 지원을 확인한 뒤 현재 활성 Orca 프로필에만 적용합니다. 기존 실행 인자와 다른 설정은 유지합니다. 기본 명령(빈 값 또는 `codex`)만 자동 변경하며, 사용자 지정 명령은 덮어쓰지 않고 로그로 안내합니다. 직접 설정하거나 해당 설치 항목을 선택 해제하세요. 다른 프로필을 사용하면 그 프로필에서도 다시 적용해야 합니다.

Windows `%APPDATA%\orca`의 기존 프로필 JSON 또는 검증된 SQLite 스키마 3을 지원합니다. DB가 있으면 호환용 JSON을 수정하지 않고 설정 행의 해시·리비전과 프로필 리비전을 함께 갱신합니다. 미반영 JSON 변경·다른 스키마·손상된 설정은 수정하지 않습니다. 변경 전 같은 폴더에 `*.before-codex-no-daemon.*.bak` 백업을 만들며, 백업에는 개인 설정이 포함되므로 공유하지 마세요. 복구할 때는 Orca를 종료하고 JSON 백업은 원래 파일로, DB 백업은 기존 DB와 `-wal`/`-shm`을 별도 보관한 뒤 `profile-state.db`로 복원합니다. 소스에서 실행할 때도 `python3 windows/prepare-orca-runtime.py`로 동봉 런타임을 먼저 준비하세요.

자동 검사 경로는 `%LOCALAPPDATA%\Programs\orca`입니다.
수동 패치는 **검증된 Windows Orca 1.4.202/1.4.215 app.asar만** 지원합니다. 업데이트하면 로컬 패치가 사라질 수 있습니다. 설치 구성에서 **Orca 패치 누락 감시**를 선택하면 로그인 시와 5분마다 누락·미검증 버전을 확인해 알립니다. 감시는 앱을 수정하거나 업데이트를 차단하지 않습니다. Orca 스킬·패치와 독립적으로 선택할 수 있고, 기존 감시 파일이 오래됐거나 예약 작업이 비활성화돼 있으면 재설치합니다. 선택 해제는 새 실행에서 설치를 건너뛰는 동작이며, 기존 감시는 패치 안내의 제거 명령으로 삭제합니다. 자세한 지원·복구·감시 제거 방법은 [패치 안내](windows/patches/README.md)를 참고하세요.
**Orca 자동 재패치**를 선택하면 업데이트 후 이름 생성·터미널 출력 복원 패치를 각각 검사합니다. 수정 전 코드가 확인되는 경우만 적용하며, 공식 업데이트나 로컬 패치로 이미 수정된 코드는 유지합니다. 판별할 수 없는 코드 변경은 검토 알림으로 안내합니다. 엔진과 전용 Windows Node 런타임이 EXE에 포함되어 있어 저장소 다운로드나 별도 Windows Node 설치가 필요 없습니다. WSL·개발 도구·Orca 자체 설치에는 기존과 같이 인터넷이 필요합니다. 알려진 원본 해시 또는 엄격히 일치하는 함수 구조에만 적용하며, 원본을 백업하고 파일 잠금이 풀릴 때까지 기다립니다. 앱을 강제 종료하거나 공식 업데이트를 막지 않습니다. 처리할 수 없는 버전은 알림으로 안내합니다.
자동화는 기본 선택 해제 상태이며, 설치 완료와 현재 패치 적용 완료는 구분합니다. 설치 직후와 로그인 때 창 없이 시작하며, 1분마다 재실행하지 않고 파일 변경을 감시해 업데이트 시 검사·재패치합니다. 알림만 원하면 기존 감시 항목을, 자동 복구까지 원하면 자동 재패치 항목을 선택하세요. 두 항목을 함께 선택하면 알림이 중복될 수 있습니다. 선택 해제는 기존 자동화를 제거하지 않습니다. [자동 재패치 운영·제거 안내](windows/orca-auto/README.md)를 참고하세요.

아래는 버전별 **수동 패치**의 동작입니다.
원본과 결과 SHA-256을 확인하며 원본을 `resources/app.asar.bootstrap-wsl-rename.<버전>.original`에 백업합니다.
다른 버전은 수정하지 않습니다. 앱을 자동 종료하거나 업데이트 후 자동 재패치하지 않습니다.
사용자 지정 경로의 패치는 아래 CLI를 사용합니다.

```powershell
powershell -ExecutionPolicy Bypass -File windows\fix-orca-wsl-rename.ps1 -AppDir 'D:\Apps\orca'
# 패치된 파일을 검증된 백업으로 복원
powershell -ExecutionPolicy Bypass -File windows\fix-orca-wsl-rename.ps1 -Restore
```

## 중단, 실패, 다시 실행

- 필수 단계가 실패하면 해당 단계에 의존하는 작업은 대기합니다. 독립 작업은 계속합니다.
- 인증·Orca 준비가 필요하면 **사용자 작업 필요**로 표시합니다.
- **현재 단계 후 중지**는 실행 중인 명령이 끝난 다음 멈춥니다. 전체 자동 롤백은 하지 않습니다.
- 앱을 강제 종료했거나 PC가 재부팅되어도 다시 열고 환경 확인 후 재실행할 수 있습니다.
- 이전 성공 기록만 믿지 않고 실제 명령과 파일을 다시 검사합니다.
- 같은 Ubuntu에서 설치가 중복 실행되지 않도록 잠금을 사용합니다.
- WSL 재시작은 실행 중인 모든 WSL 작업을 종료하므로 앱에서 먼저 안내합니다.

앱 설정과 기록: `%LOCALAPPDATA%\dev-bootstrap`

- `state.json`: 선택 구성과 화면 상태
- `run-<시간>/config.json`: 해당 실행의 구성
- `run-<시간>/events.jsonl`: 단계별 상태
- `run-<시간>/events.log`: 설치 명령 출력

로그인 터미널의 출력은 설치 로그로 수집하지 않습니다. 로그는 **로그 폴더 열기** 버튼으로 확인합니다.

## CLI로 설치하기

앱 없이 설치하는 경로도 유지합니다. **이제 비대화형 실행에는 명시적인 JSON 구성이 필요합니다.**
기존 `GIT_USER_NAME=... bash setup.sh` 형태 대신 구성 파일의 `gitName` / `gitEmail`과 해당 선택 항목을 사용하세요.

### 새 Windows PC

관리자 PowerShell에서 실행합니다. 저장소 clone은 필요하지 않습니다.

```powershell
irm https://raw.githubusercontent.com/Muring/muring-dev-setup/main/windows/bootstrap.ps1 -OutFile "$env:TEMP\bootstrap.ps1"
powershell -ExecutionPolicy Bypass -File "$env:TEMP\bootstrap.ps1" -User muring
```

저장 위치 메뉴를 선택하고 진행합니다. WSL 설치 시 재부팅을 요구하면 재부팅 후 같은 명령을 실행합니다.
위치 기능을 지원하지 않는 경우 `wsl --update`를 실행합니다.
WSL 자체가 없으면 `wsl --install --no-distribution`부터 실행합니다.

```powershell
# 위치 지정
powershell -ExecutionPolicy Bypass -File "$env:TEMP\bootstrap.ps1" -User muring -InstallDrive D
# 비대화형 Ubuntu 설정: JSON 파일 경로 전달
powershell -ExecutionPolicy Bypass -File "$env:TEMP\bootstrap.ps1" -User muring -ConfigFile 'C:\Setup\config.json'
```

구성 파일을 생략하면 Ubuntu에서 구성 선택 메뉴가 이어집니다.
CLI의 설치 저장소는 `~/dev/dev-bootstrap`이며 기존 checkout은 자동 업데이트하지 않습니다.
앱에 포함된 설치 버전과 GitHub main의 CLI 버전은 다를 수 있습니다.

### 기존 Ubuntu

Ubuntu 터미널에서 일반 개발 계정으로 실행합니다. 전체 스크립트를 sudo로 실행하지 않습니다.

```bash
mkdir -p ~/dev
git clone https://github.com/Muring/muring-dev-setup.git ~/dev/dev-bootstrap
bash ~/dev/dev-bootstrap/linux/setup.sh
```

저장소가 이미 있다면 clone은 생략합니다. 대화형 메뉴에서 권장 항목과 설정을 확인합니다.
비대화형 실행 예시:

```bash
bash ~/dev/dev-bootstrap/linux/setup.sh --config ~/bootstrap-config.json
# 선택된 한 단계만 재시도: 의존성도 실제 상태를 다시 확인
bash ~/dev/dev-bootstrap/linux/setup.sh --config ~/bootstrap-config.json --step kb
# 설치 없이 선택 항목 상태 검사
bash ~/dev/dev-bootstrap/linux/setup.sh --config ~/bootstrap-config.json --check
```

최소 구성 예시:

```json
{
  "version": 1,
  "profile": "common",
  "selected": ["base", "node", "gh"],
  "distro": "Ubuntu",
  "user": "developer",
  "installLocation": "",
  "gitName": "",
  "gitEmail": "",
  "timezone": "Asia/Seoul",
  "kbRepo": "https://github.com/Muring/muring-kb.git",
  "kbDir": "~/dev/muring-kb"
}
```

구성 목록과 의존성의 원본은 `shared/catalog.json`입니다.
CLI 기록은 `~/.local/state/dev-bootstrap/`에 저장됩니다.
`--events <경로>`로 JSONL 위치를 바꿀 수 있고 `.log`와 `.stop`은 같은 이름의 확장자를 사용합니다.
KB만 따로 재시도하는 `linux/setup-kb.sh`도 유지합니다.

## 앱 개발과 빌드

개발자 빌드 환경에는 Node 22.23.2 이상, npm, Python 3가 필요합니다. 일반 사용자에게는 필요 없습니다.

```bash
cd app
npm ci
npm run build
npm test
npm run dist:win
```

빌드 시 고정 SHA-256으로 검증한 Windows Node 런타임과 라이선스를 내려받아 EXE에 동봉합니다. 사용자 PC에서는 자동 재패치 실행을 위해 추가 다운로드하지 않습니다. CLI 소스에서 설치할 때는 먼저 `python3 windows/prepare-orca-runtime.py`로 런타임을 준비하세요.

Windows 포터블 산출물: `app/release/MuRingDevSetup-<package.json의 버전>-x64.exe`

현재 버전은 0.1.14입니다. 기존 릴리스는 교체하지 않습니다.

Windows에서 개발용 앱을 실행하려면 `npm start`를 사용합니다.
현재 소스는 초기 환경 조회 실패 시 오류와 **다시 시도** 버튼을 표시합니다. 재시도는 초기 데이터를 다시 읽으며 설치 작업을 실행하지 않습니다.
Linux에서 실행하면 화면 개발만 가능하며 Windows 설치 기능은 차단됩니다.
첫 버전에는 코드 서명, 자동 업데이트, 공개 릴리스 자동 게시를 포함하지 않습니다.

구조:

- `app/`: Electron 메인 프로세스, 제한된 preload API, React 설치 마법사
- `shared/catalog.json`: 두 진입점이 공유하는 설치 항목과 의존성
- `windows/app-host.ps1`: Windows 검사, WSL 준비, Ubuntu 설치, 실행 터미널
- `linux/runner.py`: JSON 구성 검증, 의존성 순서, 중지·재실행, JSONL 상태
- `linux/steps.sh`: 각 단계의 검사·적용·검증
- `linux/lib/shell_config.py`: 기존 셸 설정 보존과 관리 파일 연결

Electron 화면에는 Node 접근을 주지 않습니다. 원격 웹페이지를 앱 안에 로드하지 않으며,
프로세스 실행은 검증된 작업 ID와 인자 배열로만 수행합니다. Windows 관리자 권한은
WSL 시스템 준비 helper에만 사용하고 Ubuntu·사용자 설정은 원래 계정 기준으로 실행합니다.

## 검증

시스템을 설치하지 않는 테스트:

```bash
python3 tests/content-update.py
python3 tests/setup-order.py
python3 tests/shell-config.py
python3 tests/setup-kb.py /path/to/muring-kb
cd app
npm test
npm run build
npx playwright install --with-deps chromium
npm run test:ui
npm run format:check
```

앱 소스는 Prettier 형식을 유지합니다. 수정 후 `npm run format`으로 정리합니다.

Windows PowerShell에서:

```powershell
powershell -ExecutionPolicy Bypass -File tests\app-host.ps1
powershell -ExecutionPolicy Bypass -File tests\wsl-location.ps1
powershell -ExecutionPolicy Bypass -File tests\orca-wsl-rename.ps1 -OriginalArchive '<검증된 원본 app.asar>'
```

`app-host.ps1` 테스트는 파싱·인자 전달, wsl.exe의 UTF-16LE 메시지와 Linux UTF-8 출력 디코드, 실제 Windows 환경의 읽기 전용 검사, WSL 미설치 스텁에서의 준비 필요 판정과 Ubuntu 설치 거부, 별도 WSL 창의 인자 전달을 확인합니다.
설치 실행기 테스트는 가짜 외부 명령을 사용하고, KB 테스트는 임시 홈과 로컬 원본을 사용합니다.

현재 확인한 범위: 고정 화면·단계 잠금·Orca 다운로드 검증 테스트, 구성·의존성 테스트, 임시 홈의 셸/Git 설정 보존, KB 회귀 테스트,
브라우저 UI 테스트, 실제 Windows helper 및 WSL 인자 전달, 패키징된 Windows 앱의
preload·IPC·읽기 전용 WSL 검사, 실제 GitHub 콘텐츠 미리보기와 구성 화면입니다.
콘텐츠 테스트는 임시 홈에서 버전 고정·백업·충돌 보존·실패 복구를 검증하고, 실제 GitHub 다운로드와 Claude/Codex 원본 일치도 확인했습니다.
Orca 패치 회귀 테스트는 검증된 원본 app.asar를 확보하지 못해 이번 검증에서 실행하지 않았습니다.

Orca 설치 파일의 실제 다운로드·체크섬 검증을 확인했습니다. 새 Windows에서 Orca 설치 창을 끝까지 진행하는 검증은 아직 남아 있습니다.

**신규 Windows VM에서 WSL 설치 → 재부팅 → Ubuntu 생성 → 전체 설치의 실환경 검증은 아직 완료하지 않았습니다.**
자동 테스트와 패키징 성공이 신규 PC 설치 전체의 성공을 의미하지는 않습니다.
실패 시 단계별 기록을 확인하고, 수정 후 같은 구성으로 다시 실행하세요.

PowerShell 파일은 UTF-8 BOM, 셸 스크립트는 LF를 유지합니다.
개인 KB 내용, 계정 토큰, 프로젝트 비밀값을 이 public 저장소에 넣지 않습니다.

사용량의 지속 수집·양식 승인·정기 실행·작업 결과 기록은 [usage-report 추적 안내](skills/usage-report/references/tracking.md)를 따릅니다. 설치만으로 타이머가 활성화되지 않습니다.

`usage-report`의 `scripts/usage_publish.py`는 기존 집계를 블로그 대시보드로 내보냅니다. 전송은 `--send`와 별도 HTTPS 수집 API·비밀키가 설정된 환경에서만 실행하며, 로컬 수집 설치만으로 공개하지 않습니다. [연결 절차](skills/usage-report/references/tracking.md#블로그-집계-내보내기)를 참고하세요.
