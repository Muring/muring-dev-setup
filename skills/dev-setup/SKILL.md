---
name: dev-setup
description: Windows 또는 Ubuntu에서 선택 가능한 개발환경 설치를 진행한다. 개인 KB 외 업무 프로젝트 clone과 비밀값 설정은 포함하지 않는다.
---

# 개발환경 구축

현재 환경을 확인하고 README의 앱 또는 CLI 경로를 사용한다.

- Windows에서는 설치 마법사를 우선한다. 기존 Ubuntu를 이동·삭제하지 않는다.
- Ubuntu에서는 별도로 설치된 자산의 `linux/setup.sh`를 사용한다. 콘텐츠 디렉터리에는 설치 코드가 없다.
  앱 설치의 자산은 `~/.local/share/dev-bootstrap/runtime`, CLI checkout은 보통 `~/dev/dev-bootstrap`이다.
- 기존 자산이나 checkout을 자동 pull하지 않는다. Git 작업은 사용자가 요청한 범위에서만 한다.

## 구성과 실행

1. 사용자의 설치 대상과 이미 정한 선택을 확인한다. 항목·의존성·프로필의 원본은 `shared/catalog.json`이다.
2. 기본 프로필은 MuRing이며 공통 구성도 제공한다. `Recommended`는 강제가 아니다.
   기존 `.zshrc` 보존이 기본이며 전체 교체, Git 설정 변경, Claude 권한 경고 생략, Orca 패치는 별도 선택이다.
3. 비대화형 실행에는 명시적인 JSON 구성을 전달한다.
   `bash <설치 자산>/linux/setup.sh --config <구성 파일>`
   대화형 터미널에서는 구성 파일 없이 실행해 메뉴를 사용할 수 있다.
4. 사용자가 이미 승인한 구성을 다시 묻지 않는다. 이름·이메일·저장 위치를 임의로 만들지 않는다.
5. 선택한 단계만 설치하고 검증한다. 미선택 항목의 부재를 실패로 취급하지 않는다.

## 로그인·재시작·실패 처리

- 로그인은 별도 Ubuntu 터미널에서 `gh auth login --hostname github.com`, `claude auth login`, `codex login`으로 진행한다.
- KB는 저장소 읽기 권한이 필요하다. 기존 checkout은 자동 pull하지 않는다. 등록 후 새 Codex 세션을 사용한다.
- Orca 앱은 직접 설치·로그인한 후 대상 WSL 터미널을 열어 브리지를 준비한다.
  스킬 설치가 먼저이며, 선택한 패치를 적용할 때만 앱 종료를 안내한다. 임의로 앱을 종료하지 않는다.
- Orca 패치는 검증된 Windows 1.4.202/1.4.215 파일에만 적용한다. 미지원 파일은 수정하지 않는다.
- Windows 또는 WSL 재시작 안내가 있으면 실행 중인 작업에 대한 영향을 알리고 사용자가 정한 시점에 진행한다.
- 앱의 로그는 `%LOCALAPPDATA%\dev-bootstrap`, CLI 로그는 `~/.local/state/dev-bootstrap`에 있다.
- 실패하면 이벤트와 로그를 읽고 해당 단계를 재시도한다:
  `bash <설치 자산>/linux/setup.sh --config <구성 파일> --step <항목 ID>`
- 재실행은 실제 상태를 검사한다. 설치 완료와 계정 연결 상태를 구분하고 미검증 항목을 완료라고 보고하지 않는다.
- 스킬·커맨드 경로가 기존 일반 디렉터리와 충돌하면 내용을 보존하고 알린다. 자동 삭제하지 않는다.
