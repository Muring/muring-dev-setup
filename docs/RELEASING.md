# 다음 버전 배포

사용자는 Releases에서 EXE만 다운로드합니다. Git clone과 아래 절차는 개발자에게만 필요합니다.
검증이 끝나지 않은 버전은 Pre-release로 게시하고, 신규 Windows 전체 설치 검증을 마친 뒤 안정판 여부를 결정합니다.

릴리스 표시 이름과 Git 태그는 모두 배포 EXE 파일명과 동일하게 지정합니다(예: `MuRingDevSetup-0.1.11-x64.exe`).
검증판 여부는 GitHub의 Pre-release 표시로 구분합니다.

저장소 개명 시에는 먼저 [개명 전환 절차](RENAMING.md)를 확인합니다.
기존 릴리스의 `DevBootstrap-*` 파일명과 태그는 유지하고, 새 버전부터 `MuRingDevSetup-*`을 사용합니다.

## 콘텐츠만 변경한 경우

`commands/`, `skills/`만 변경했다면 EXE를 다시 빌드하거나 릴리스하지 않습니다.
원본은 일반 파일 `skills/<name>/SKILL.md`이며 `commands/<name>.md`는 상대 링크로 유지합니다.
`python3 tests/content-update.py`로 형식과 업데이트 동작을 검증한 뒤 검토한 파일을 commit/push합니다.
사용자는 0.1.1 이상 앱의 **커맨드 · 스킬 업데이트 → 업데이트 확인 → 확인한 버전 적용**을 사용합니다.
설치기의 동작·UI·항목 구조를 바꿨다면 아래 새 EXE 배포 절차를 따릅니다.

## 1. 버전과 문서

저장소 루트에서 실행합니다. 아래 `0.1.11`은 다음 버전 예시이며 이미 배포한 버전을 재사용하지 않습니다.

```bash
cd app
npm version 0.1.11 --no-git-tag-version
cd ..
```

`docs/releases/v0.1.11.md`에 변경 동작, 설치 순서, 검증 결과와 남은 한계를 작성합니다.
README의 다운로드·릴리스·체크섬 링크와 EXE 이름도 새 버전으로 바꿉니다.

## 2. 검증과 빌드

```bash
python3 tests/content-update.py
python3 tests/setup-order.py
python3 tests/shell-config.py
# 로컬 KB 원본이 있는 경우
python3 tests/setup-kb.py /path/to/muring-kb
cd app
npm ci
npm run format:check
npm test
npm run build
# UI 테스트 환경을 처음 준비할 때: npx playwright install --with-deps chromium
npm run test:ui
npm run dist:win
cd ..
```

Windows에서는 `tests/app-host.ps1`, `tests/wsl-location.ps1`, `tests/orca-wsl-monitor.ps1`도 실행합니다. 감시 검사는 임시 예약 작업을 생성하고 삭제합니다.
검증된 원본이 있을 때 `tests/orca-wsl-rename.ps1`을 실행하고, 없는 경우 미검증으로 명시합니다.
깨끗한 Windows VM의 WSL 준비·재부팅·Ubuntu 생성·설치·인증과 기존 설정 보존 시나리오는 별도로 확인합니다.

패키징한 앱을 **Windows 로컬 폴더**에서 실행해 환경 검사와 화면을 확인합니다.
WSL 공유 경로의 unpacked Electron 실행은 Windows의 프로세스 실행 제약 때문에 검증 환경으로 사용하지 않습니다.
앱이나 설치 스크립트 소스를 수정했다면 EXE도 다시 빌드합니다. 소스와 일치하지 않는 이전 EXE를 올리지 않습니다.

## 3. 소스와 태그 push

```bash
git diff --check
git status --short
# 검토한 소스·문서만 명시적으로 추가합니다. EXE와 로컬 로그는 추가하지 않습니다.
git add <검토한 파일들>
git commit -m "release: prepare muring dev setup v0.1.11"
git push origin main
git tag -a MuRingDevSetup-0.1.11-x64.exe -m "MuRingDevSetup-0.1.11-x64.exe"
git push origin MuRingDevSetup-0.1.11-x64.exe
```

## 4. 초안 업로드, 확인, 공개

다음 예시는 Bash/WSL에서 실행합니다.

```bash
(cd app/release && sha256sum MuRingDevSetup-0.1.11-x64.exe > SHA256SUMS.txt)
gh release create MuRingDevSetup-0.1.11-x64.exe \
  app/release/MuRingDevSetup-0.1.11-x64.exe app/release/SHA256SUMS.txt \
  --verify-tag --draft --prerelease \
  --title "MuRingDevSetup-0.1.11-x64.exe" \
  --notes-file docs/releases/v0.1.11.md
```

초안에서 소스 태그, EXE 이름·크기, 체크섬 파일을 확인합니다. GitHub API가 제공하는
EXE asset의 `digest`와 로컬 SHA-256을 대조합니다. 그 뒤 공개합니다.

```bash
gh release view MuRingDevSetup-0.1.11-x64.exe --json url,assets,isDraft,isPrerelease
gh release edit MuRingDevSetup-0.1.11-x64.exe --draft=false
```

공개 후 로그인 없는 다운로드 링크가 열리는지 확인하고, 사용자에게 다음을 함께 전달합니다.

- EXE 직접 다운로드 링크와 릴리스 페이지
- 새 PC에서 실행할 순서와 기존 PC에서 재실행할 방법
- 확인한 범위와 아직 검증하지 않은 범위
- 실패 시 로그 위치와 다음 버전 다운로드 방법

Pre-release는 `/releases/latest`에서 보이지 않을 수 있으므로 버전별 직접 링크를 사용합니다.
EXE 교체가 필요하면 기존 릴리스 파일을 조용히 덮어쓰기보다 버전을 올려 변경 내용을 남깁니다.
