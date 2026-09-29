---
name: blog-draft
description: 지금까지의 대화와 프로젝트 이력을 재료로 mublog 개발기 말투의 포스트를 쓰고, 블로그에 초안으로 등록한다
allowed-tools: Bash, Read, Glob, Grep, Write
---

## Context

Claude Code에서는 `/blog-draft`, Codex에서는 `$blog-draft`로 호출한다.
재료를 수집할 대상은 사용자가 현재 작업 중인 저장소이며 이 명령 파일의 저장 위치가 아니다.
다음 읽기 전용 명령으로 오늘 날짜와 저장소를 확인한다. Git 저장소일 때만 최근 커밋을 읽는다.
Git 저장소가 아니거나 이력이 없으면 그 사실을 기록하고 대화·문서를 재료로 사용한다.

```bash
TZ=Asia/Seoul date +%F
git rev-parse --show-toplevel
git log --oneline -60
```

## 입력

`$ARGUMENTS` — 앞의 `kebab-case` 토큰이 있으면 slug, 나머지는 주제 힌트나 커밋 범위(`abc123..HEAD`, `--since=2026-08-01`)다.
Codex에서는 `$ARGUMENTS`를 자동 치환 변수 대신 호출과 함께 전달한 입력으로 해석한다.
아무것도 없으면 slug 도 주제도 직접 정한다.

**블로그 저장소 경로**는 `$MUBLOG_DIR`, 없으면 `$HOME/dev/mublog` 다.
아래에서 `$MUBLOG` 로 줄여 쓴다. 없으면 거기서 멈추고 경로를 묻는다.

셸이 zsh 다. `src/app/[slug]/` 처럼 대괄호가 든 경로는 **큰따옴표로 감싼다** —
안 감싸면 glob 으로 읽혀 `no matches found` 로 죽는다. `--include=*.ts` 같은
인자도 마찬가지다.

## 1. 재료

**git 은 필수가 아니다.** 아래 순서로 있는 것을 쓴다.

1. **지금까지의 이 대화** — 가장 좋은 재료다. 무엇을 하려다 무엇에 막혔고 왜 그렇게 풀었는지가
   커밋 메시지보다 훨씬 자세히 남아 있다. 이 세션에서 함께 고친 것이 있으면 그것이 글의 뼈대다.
2. **git 이력** — 위 Context 에 커밋이 보이면 더 판다. 없으면 그냥 넘어간다.
   인계문(session-brief)이 있다면 현재 HEAD와 대조해 확정 결정·검증 근거부터 재사용한다. 없는 이유를 추측하거나 전체 세션 로그를 다시 읽지 않는다.
3. **코드와 문서** — `README.md`, `CLAUDE.md`, `package.json`, 주요 설정 파일.

셋 다 없고 대화도 짧으면, 지어내지 말고 **무엇에 대해 쓸지 사용자에게 묻는다.**

git 이 있을 때만:

```bash
git log --reverse --date=short --pretty='%h %ad %s' <범위>
git log --reverse --pretty='%s%n%b' <범위>      # 커밋 본문에 이유가 적혀 있다
git diff --stat <범위> | tail -40
```

커밋 메시지만으로 "왜" 가 안 보이면 **그 커밋의 diff 를 열어본다.** 추측으로 메우지 않는다.

블로그 쪽 어휘는 항상 확인한다:

```bash
ls "$MUBLOG/public/thumbnails"
grep -h -A6 '^tags:' "$MUBLOG"/backup/posts/*.mdx | grep '^    - ' | sort -u
ls "$MUBLOG/backup/posts"      # 기존 slug (중복 회피)
```

## 2. 말투와 구조

**`$MUBLOG/backup/posts/blog-development-4.mdx` 를 먼저 읽는다.** 그 글이 기준이다.
아래는 그 글에서 뽑은 체크리스트다.

**말투**

- 평어체 `~다`. 1인칭 `나`. 이미 끝난 일을 돌아보는 과거 시제.
- 문장이 짧다. 한 문단은 2~4문장. 한 문단에 주장 하나.
- **볼드는 문장 전체가 아니라 핵심 주장 한 덩어리에만.** 한 절에 한두 번.
- `> *"..."*` 형태의 혼잣말 인용을 글 전체에 2~4번. 결정을 내린 순간이나 자조 섞인 한 줄.
- 실패와 삽질을 감추지 않는다. 틀렸던 판단은 틀렸다고 적는다.
- 과장하지 않는다. "완벽하게", "혁신적인" 같은 말을 쓰지 않는다.
- **AI 와 함께 고쳤다는 사실을 글의 소재로 삼지 않는다.** 내가 판단하고 내가 고친 것으로 적는다.

**구조**

1. **도입** — 무엇이 불편했는지부터. 문제 상황 → 왜 짜증났는지 → 인용 한 줄 → "그래서 ~하기로 했다".
   규모를 숫자로 줄 수 있으면 준다("커밋은 76개"). **실제로 센 값이 있을 때만.**
2. **`---` 로 큰 절을 나눈다.** `##` 절은 3~6개.
3. `##` 제목은 짧은 명사구나 문장("무엇을 쓸 것인가", "DB 설계", "그리고 나서 마주친 것들").
4. `###` 소제목은 **판단이나 결론을 그대로 적는다** — "태그를 별도 테이블로 빼지 않았다",
   "조용히 깨지는 게 제일 무섭다". 명사 나열("태그 설계")로 두지 않는다.
5. **선택지 비교·전후 비교는 표로.** 문단으로 늘어놓지 않는다.
6. 코드블록은 요점만 5~15줄. 언어 태그를 반드시 붙인다. 파일 전체를 붙여넣지 않는다.
7. 끝에서 두 번째 절은 **`## 결과`** — 무엇이 달라졌는지. 전후 표나 사라진 단계 목록.
8. 마지막 절은 **`## 느낀점`** — `- **한 줄 주장.** 근거 한두 문장` 형태의 불릿 3~5개.
   그 아래 마무리 한두 문단, 마지막은 읽어준 사람에게 감사.

**분량** 본문 6,000~12,000자. 재료가 적으면 억지로 늘리지 말고 짧게 쓴다.

## 3. 지켜야 할 것

- **확인한 것만 쓴다.** 모든 주장은 이 대화·커밋·diff·코드에서 근거를 봤어야 한다.
  숫자(커밋 수, 소요 일수, 응답 시간, 파일 개수)는 실제로 세거나 잰 값만. 없으면 그 문장을 뺀다.
- **이미지는 `public/images/<slug>/` 경로로 넣지 않는다.** 새 글의 그 폴더는 비어 있고 커밋·배포 전까지
  깨져 보인다. 스크린샷을 넣을 수 있는 환경(4-2)이면 storage 에 올린 URL 만 본문에 쓴다. 그 환경이 아니면
  본문에 이미지를 넣지 않고 "여기에 이 스크린샷이 있으면 좋겠다" 를 **마지막 보고에만** 목록으로 적는다.
- **태그는 기존 어휘에서 고른다**(1에서 뽑은 목록). 새 태그는 정말 필요할 때만, 최대 3개.
  `etc` 는 항상 마지막.
- **썸네일은 실제로 있는 것만.** `$MUBLOG/public/thumbnails` 의 파일이거나, 이미 올라간 storage URL
  (`backup/posts/*.mdx` 의 `thumbnail:` 값 참고). 마땅한 게 없으면 줄을 빼고 마지막 보고에 적는다.
  블로그 개발기 시리즈 일러스트는 Codex 의 `image_gen` 으로 만든다 — 스타일 프롬프트와 업로드 절차는
  `$MUBLOG/output/imagegen/blog-development-thumbnails/` 의 `manifest.json`·`publish.mjs` 가 원본이다.
  Claude Code 에는 이미지 생성 도구가 없으므로 생성은 Codex 에서 하고, 여기서는 URL 만 쓴다.
- **slug 는 소문자·숫자·하이픈만.** 기존 slug 와 겹치지 않게 한다.
- 회사·고객사 이름, 비밀값, 사내 URL, 실제 계정명을 본문에 넣지 않는다.

## 4. 파일 쓰기

프론트매터는 아래 형식을 그대로 지킨다(들여쓰기 4칸, `status` 는 반드시 `draft`):

```
---
title: "제목"
date: "YYYY-MM-DD"
description: "한 줄 요약 - 300자 이내"
tags:
    - frontend
    - etc
thumbnail: "/thumbnails/파일명.jpg"
status: "draft"
---
```

`date` 는 위 Context 의 오늘(KST) 날짜다.

**제목과 설명은 짧게 쓴다**(사용자 지시, 2026-09-18 재확인). 기존 글이 기준이다 —
제목 `블로그 개발기 4 (백엔드 편)`, 설명 `정적 블로그를 DB 기반으로 갈아엎은 기록 - Supabase 설계부터 배포 후 만난 함정까지`.

- `title` 은 **24자 안**(기존 글 최대가 23자다). 시리즈면 `<시리즈명> <n> (<주제> 편)` 꼴. 부제를 ` - ` 로 잇지 않는다.
- `description` 은 **60자 안**, 한 문장. 나열(`A, B, 그리고 C까지`)로 늘리지 않는다.
- 300자는 스키마 상한이지 목표가 아니다. 넘치면 본문 도입부로 보낸다.
파일은 **스크래치패드에 `<slug>.mdx`** 로 쓴다(파일명이 곧 slug 다).

## 4-1. 썸네일 — Codex 에서만

Claude Code 에는 이미지 생성 도구가 없다. Claude 에서 실행 중이면 이 절을 건너뛰고 6번 보고에
"썸네일은 Codex 에서 `$blog-draft` 로 생성" 한 줄을 남긴다. Codex 에서는 등록 전에 다음을 한다.

1. `$MUBLOG/output/imagegen/blog-development-thumbnails/` 를 연다. `manifest.json` 과
   `blog-development-8-prompt.json` 이 시리즈 스타일 프롬프트의 원본이고, 직전 편 `blog-development-<n-1>.png` 가
   스타일 참조 이미지다. 프롬프트의 스타일 문장(Warm ivory·navy·cobalt·teal·orange, paper texture, 16:9, no text)은
   그대로 두고 **구성 부분만 이번 글 주제로** 바꾼다.
2. `image_gen` 으로 한 장 만들고 `<slug>.png` 와 `<slug>-prompt.json`(사용한 프롬프트·참조 파일)을 같은 폴더에 둔다.
3. 올리기 전에 사용자에게 이미지를 보여 주고 확인을 받는다. 마음에 안 들면 프롬프트만 바꿔 다시 만든다.
4. 확인되면 **올릴 파일을 JPEG 로 줄인다.** `image_gen` PNG 는 1672×941·약 1.7MB 인데, 가장 크게 쓰이는 곳이
   카드(2x 에서 828px)와 OG(360px 정사각)라 1200px 이면 충분하고 JPEG q82 로 약 70KB 가 된다(눈으로 구분 안 됨).
   **WebP 는 쓰지 않는다** — OG 이미지를 그리는 satori 가 WebP 를 못 읽어 `opengraph-image` 가 실패한다.
   원본 PNG 는 폴더에 그대로 두고, 저장소 루트에서 변환한다.

   ```bash
   cd "$MUBLOG" && node -e 'require("sharp")(process.argv[1]).resize({width:1200,withoutEnlargement:true}).jpeg({quality:82,mozjpeg:true}).toFile(process.argv[2]).then(i=>console.log(i.width+"x"+i.height, i.size+"B"))' \
     output/imagegen/blog-development-thumbnails/<slug>.png output/imagegen/blog-development-thumbnails/<slug>.jpg
   ```
5. 그 `.jpg` 를 `publish.mjs` 의 업로드 방식대로 올린다 — 경로는 `thumbnails/<slug>/illustration-<sha256 앞 12자리>.jpg`
   (해시도 `.jpg` 바이트로), `contentType: "image/jpeg"`, `upsert: false`, 올린 뒤 공개 URL 을 받아와 바이트가 같은지 확인. **`publish.mjs` 는 1~7편 slug 가 박혀 있는
   일회성 스크립트**라 그대로 돌리지 말고, 업로드 부분만 이번 slug 로 쓴다. 새 초안은 아직 DB 에 없으므로 posts
   UPDATE 는 하지 않는다.
6. 받은 공개 URL 을 프론트매터 `thumbnail:` 에 넣는다. 그다음 5번 등록으로 간다.

비밀값(`SUPABASE_SECRET_KEY`, `DATABASE_URL`)은 `.env.local` 에서 읽기만 하고 출력·복사하지 않는다.

## 4-2. 스크린샷 — Orca 안에서만

터미널·저장소 화면을 글에 넣고 싶을 때 쓴다. **`ORCA_CLI_COMMAND` 가 설정된 Orca 터미널에서만** 가능하다.
아니면 이 절을 건너뛰고 6번 보고에 넣을 위치만 적는다. 이미지 처리 도구는 `$MUBLOG/node_modules/sharp` 를
쓰므로 블로그 저장소의 의존성이 설치돼 있어야 한다. 아래 `ORCA` 는 `$ORCA_CLI_COMMAND` 의 값이다.
도우미 스크립트는 이 명령 파일 옆 `scripts/` 에 있다. 아래 `$SCRIPTS` 는 그 경로다.

```bash
SCRIPTS="${CODEX_HOME:-$HOME/.codex}/skills/blog-draft/scripts"
```

**무엇을 찍을지 먼저 정한다.** 한 절에 한 장이면 충분하다. 빈 화면이 많은 캡처는 넣지 않는다.

1. **장면 만들기** — 전용 터미널에서 명령을 실행하고 그 탭으로 전환한다.

   ```bash
   ORCA terminal create --worktree path:<대상 저장소> --title "shots" --json   # handle 을 받는다
   ORCA terminal send --terminal <handle> --text "clear; <명령>" --enter --json
   ORCA terminal switch --terminal <handle> --json
   ```

   대화형 메뉴는 `send --text 3 --enter` 로 진행하고 끝나면 `q` 로 나간다.

2. **창 캡처** — Orca 창 전체가 PNG 로 떨어진다. 결과 경로는 Windows 임시 폴더이고 `expiresAt` 이 있으니
   바로 복사한다. WSL 에서는 `C:\` → `/mnt/c/`, `\` → `/` 로 바꿔 읽는다(zsh `sed` 의 역슬래시 치환은
   잘 깨지므로 Python 으로 바꾼다).

   ```bash
   ORCA computer list-apps --json                       # name=Orca 인 pid
   ORCA computer get-app-state --app pid:<pid> --window-index 0 --json   # result.screenshot.path
   ```

3. **잘라내기** — 첫 장을 눈으로 보고 터미널 패널의 픽셀 범위를 정한 뒤 같은 값을 재사용한다.
   **왼쪽 사이드바(다른 프로젝트 이름이 보인다)와 상태바는 반드시 뺀다.** 패널 오른쪽 위 아이콘도 범위에서
   빼야 여백 제거가 된다. 1936×1040 창에서는 대략 `290 37 1250 968` 이었다. 스크립트가 내용이 있는 부분만
   남기고 여백을 붙인 뒤 폭 1600 이하로 줄인다.

   ```bash
   node "$SCRIPTS/crop.js" <원본.png> <결과.png> <left> <top> <width> <height>
   ```

   결과를 열어 잘린 글자·개인 정보·빈 공간을 눈으로 확인한다.

4. **웹 화면** — Orca 내장 브라우저로 찍는다. `screenshot` 은 base64 PNG 를 `result.data` 에 준다.
   기본 프로필은 로그인이 없어서 private GitHub 는 404 다. 그때는 마크다운을 `$MUBLOG/src/lib/markdown/render.ts` 의
   `renderMarkdown` 으로 HTML 로 만들어 `python3 -m http.server` 로 띄우고 `ORCA goto --url http://localhost:<port>/...` 로 연다.

   ```bash
   ORCA tab create --url <url> --worktree path:<대상 저장소> --json     # browserPageId
   ORCA screenshot --page <id> --format png --json
   ORCA tab close --page <id> --json
   ```

5. **업로드** — `/api/admin/upload` 와 같은 규칙으로 `post-images` 버킷 `posts/<slug>/image-N-<8hex>.png` 에 올린다.
   `upsert: false`, 올린 뒤 공개 URL 을 받아 바이트가 같은지 확인한다. 4MB 를 넘으면 거부한다.

   ```bash
   node "$SCRIPTS/upload-images.mjs" <slug> shots/*.png --dry-run   # 경로만 확인
   node "$SCRIPTS/upload-images.mjs" <slug> shots/*.png             # "<파일명> <URL>" 출력
   ```

6. **본문 삽입** — 기준 글과 같은 형식으로 넣고 바로 아래 같은 캡션을 한 줄 더 쓴다.

   ```md
   ![*"캡션"*](https://.../post-images/posts/<slug>/image-1-xxxxxxxx.png)

   *"캡션"*
   ```

7. **정리** — 전용 터미널과 브라우저 탭을 닫고 원래 탭으로 돌아간다. 로컬 서버를 띄웠으면 끈다
   (`pkill -f` 패턴이 자기 셸 명령줄과 겹치지 않게 `serve[r]` 처럼 쓴다).

   ```bash
   ORCA terminal close --terminal <handle> --json
   ORCA terminal switch --terminal "$ORCA_TERMINAL_HANDLE" --json
   ```

비밀값(`SUPABASE_SECRET_KEY`)은 `.env` 에서 읽기만 하고 출력·복사하지 않는다. 등록 후 관리자 미리보기는
내장 브라우저에 로그인이 없으면 열리지 않으므로, 공개 URL 200 과 `renderMarkdown` 의 `<img>` 개수로 대신 확인하고
그렇게 보고한다.

## 5. 등록

```bash
cd "$MUBLOG" && yarn draft:post "<스크래치패드>/<slug>.mdx" --dry-run
```

통과하면 `--dry-run` 을 떼고 다시 실행한다. 초안으로만 들어가고 발행되지 않는다.
`slug 가 이미 있습니다` 로 실패하면 slug 를 바꿔 파일명을 고치고 다시 돌린다.
**이미 등록한 초안을 고쳐서 다시 넣을 때**는 `--update` 를 붙인다. 대상이 DRAFT 일 때만 갱신하고
발행된 글은 거부한다. 이때도 `--dry-run` 을 먼저 돌린다.

## 6. 보고

1. 등록 출력에 나온 **편집 URL** 을 그대로 준다.
2. 글의 절 목록(`##` 제목들)을 한 줄씩.
3. **스크린샷** — 4-2 로 넣은 것은 캡션·위치 목록으로, 못 넣은 것은 "넣으면 좋을 위치와 내용" 목록으로.
   캡처하지 못한 이유(Orca 밖, 로그인 필요 페이지 등)가 있으면 적는다.
4. **확인이 필요한 부분** — 근거가 약해서 뺐거나 추측이 섞였을 수 있는 지점.
5. 마지막 한 줄: `mublog 에서 yarn backup:posts 를 돌려 커밋하면 백업에도 남습니다.`
