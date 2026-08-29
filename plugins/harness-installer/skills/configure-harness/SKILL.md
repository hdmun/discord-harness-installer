---
name: configure-harness
description: Use when the user wants to install the full Discord multi-agent harness (orchestrator bot + chat-claude bot + codex/gemini bridges + usage dashboard) into a work folder, or wants to remove or inspect an existing installation. Triggers on "디스코드 하네스 설치해줘", "멀티에이전트 하네스 설치", "/configure-harness", "하네스 제거해줘", "하네스 점검해줘". 결정적 엔진(harnessctl.py)이 preflight→fetch(검증 조합 핀 체크아웃)→plugins→pair→install(오버레이+위임)→verify를 멱등 수행하고 doctor가 상시 점검한다 — 매뉴얼 16장을 대체한다. 수동은 디스코드 포탈 단계뿐(스킬이 단계별 안내).
---

# configure-harness — 디스코드 멀티에이전트 하네스 통합 설치

작업 폴더 하나를 디스코드로 운영되는 멀티에이전트 하네스(오케스트레이터 봇 + 수다
클로드 봇 + 코덱스/제미나이 브리지 + 사용량 대시보드)로 만든다. 모든 파일 조작은
결정적 엔진 `generator/harnessctl.py`가 수행한다 — 직접 plist·.env·CLAUDE.md를
손으로 쓰지 말 것. 아래 명령에서 `<이 스킬 폴더>`는 이 SKILL.md와 같은 폴더
(`skills/configure-harness`)를 가리킨다.

## 원칙 (반드시 지킬 것)

- **비파괴**: SESSION.md는 절대 만들거나 고치지 않는다. 작업 폴더 CLAUDE.md는
  엔진이 마커 블록(`<!-- discord-multiagent:start/end -->`)만 추가·제거한다.
- **토큰·웹훅 URL은 채팅으로 받지 않는다** — `pbpaste > .bot-token-<역할> &&
  chmod 600 .bot-token-<역할>` 파일 수령만. 스킬은 토큰 값을 화면에 다시
  출력하지 않는다.
- **엔진 출력은 그대로 보여준다.** 실패하면 그 단계에서 멈추고 엔진이 안내한
  다음 행동·수동 폴백을 전달한다(재량으로 대신 고치지 않는다).
- **AskUserQuestion이 없는 환경(코덱스 등)에서는 같은 질문을 채팅으로 물어
  답을 받는다.** 묻지 않고 기본값으로 질주하지 말 것(2026-08-02 코덱스 실측
  편차).

## 플랫폼 (macOS/Linux + Windows)

이 스킬은 macOS/Linux와 Windows(WSL2 배제 — 네이티브만)를 모두 지원한다. 절차는
같은 9단계이며, 셸·기동 메커니즘이 갈리는 지점만 아래 각 단계에 macOS/Windows로
나눠 병기한다(별도 SKILL-windows.md로 분리하지 않는다). 한 가지 전역 치환:
이 문서의 `python3 <경로>/harnessctl.py …` 명령은 **Windows에서 `python`으로
바꿔 실행한다**(Windows python.org 설치본은 기본적으로 `python3.exe`를 만들지
않는다). `harnessctl.py preflight`는 Windows에서 `--work-dir <설치 루트>`가
필요하다(git 레포 검사 대상 — orca terminal은 등록된 worktree 안에서만
생성된다, ADR-0001).

## 설치 절차 (9단계)

### 1. preflight

```
python3 <이 스킬 폴더>/generator/harnessctl.py preflight
```

Windows:

```
python <이 스킬 폴더>/generator/harnessctl.py preflight --work-dir <설치 루트>
```

FAIL 항목이 있으면 각 항목의 설치 방법(엔진 출력에 그대로 포함됨)을 안내하고
여기서 중단한다. macOS: `xcode-select --install` / `brew install tmux` /
`brew install node` / Claude Code 설치 / `npm i -g @openai/codex` / discord
플러그인 설치. Windows: `https://git-scm.com/download/win` / orca 설치
(`https://orca.dev`) / `winget install Microsoft.PowerShell` / node·bun 설치 /
Claude Code 설치 / `npm i -g @openai/codex` / discord 플러그인 설치 — 추가로
**작업 폴더가 git 레포인지**(아니면 FAIL, `git init` 후 재시도 — 설치기가 대신
실행하지 않는다)와 `core.longpaths`(WARN — 미설정이면 정본 레포 clone 중
'Filename too long' 가능)를 점검한다. WARN(예: `agy` 없음)은 진행 가능 —
제미나이 봇만 빠진다는 점을 알린다.

### 2. 설치 계획 질문 (AskUserQuestion 한 번에)

- **설치 루트** (기본 `~/discord-harness` — 이 폴더가 하네스의 작업 폴더가 된다)
- **봇 4개 표시 이름** (기본: 오케스트레이터·클로드·코덱스·제미나이 — 디스코드
  개발자 포탈에서 앱 이름으로 그대로 쓴다)
- **대시보드 설치 여부** (기본 예)
- **부팅 자동 기동 여부** (기본 예)

AskUserQuestion 도구가 없는 환경(예: codex)에서는 이 4개를 **채팅으로 질문해
답을 받는다.** 묻지 않고 기본값을 스스로 확정해 진행하지 말 것.

### 3. 디스코드 포탈 수동 단계 (순서대로 안내, 사용자가 끝냈다고 할 때까지 대기)

먼저 설치 루트 폴더를 만든다: `mkdir -p <설치 루트>` (이후 4번 토큰 파일 저장은
이 폴더 안에서 한다).

1. 디스코드 서버 1개 + 채널 2개(작업용·수다용) 생성. 설정 → 고급 → 개발자 모드
   켠 뒤 두 채널 각각 우클릭 → **채널 ID 복사**, 내 프로필 우클릭 →
   **사용자 ID 복사**(채팅으로 받는다 — ID는 비밀 아님).
2. https://discord.com/developers/applications 에서 봇 앱 4개 생성(2단계에서
   정한 이름 그대로). 각 앱 **Bot** 탭에서 토큰 발급 + **MESSAGE CONTENT
   INTENT** 켜기 → Save.
3. 각 앱 **OAuth2 → URL Generator**: scope `bot` 체크, Bot Permissions에서
   View Channels / Send Messages / Read Message History / Embed Links /
   Attach Files / Create Public Threads / Send Messages in Threads 체크 →
   생성된 URL로 초대. 오케스트레이터 봇은 작업 채널에만, 나머지 세 봇(클로드·
   코덱스·제미나이)은 작업+수다 채널 둘 다에 초대한다.
4. 토큰 4개는 각각 복사 직후 설치 루트가 될 폴더에서 파일로 저장한다(채팅에
   붙여넣지 않는다). macOS/Linux:
   ```
   pbpaste > .bot-token-orch    && chmod 600 .bot-token-orch
   pbpaste > .bot-token-claude  && chmod 600 .bot-token-claude
   pbpaste > .bot-token-codex   && chmod 600 .bot-token-codex
   pbpaste > .bot-token-gemini  && chmod 600 .bot-token-gemini
   ```
   Windows(pwsh — `chmod`는 무시되므로 `icacls`로 대체, 엔진 `secure_file`과
   동형):
   ```
   Get-Clipboard | Set-Content -NoNewline .bot-token-orch;   icacls .bot-token-orch   /inheritance:r /grant:r "$($env:USERNAME):F"
   Get-Clipboard | Set-Content -NoNewline .bot-token-claude; icacls .bot-token-claude /inheritance:r /grant:r "$($env:USERNAME):F"
   Get-Clipboard | Set-Content -NoNewline .bot-token-codex;  icacls .bot-token-codex  /inheritance:r /grant:r "$($env:USERNAME):F"
   Get-Clipboard | Set-Content -NoNewline .bot-token-gemini; icacls .bot-token-gemini /inheritance:r /grant:r "$($env:USERNAME):F"
   ```
5. (2단계에서 대시보드 예로 답했으면) 대시보드용 채널에 웹훅 URL을 생성한
   뒤 같은 폴더에 저장: macOS/Linux `pbpaste > .webhook-url` / Windows
   `Get-Clipboard | Set-Content -NoNewline .webhook-url`.

### 4. fetch

```
python3 <이 스킬 폴더>/generator/harnessctl.py fetch
```

정본 3레포(discord-multiagent · codex-discord · usage-coach)를 검증 조합 핀
(`generator/pins.json`)으로 clone/체크아웃한다. 최신 버전을 원하면
`--latest`(비검증 조합 — 사용자가 명시적으로 원할 때만).

### 5. plugins

```
python3 <이 스킬 폴더>/generator/harnessctl.py plugins
```

코덱스 호스트에서 실행 중이면 `--host codex`를 붙인다. 실패한 항목은 엔진이
출력하는 수동 폴백(`/plugin marketplace add …` 을 대상 호스트 대화에서 직접
실행)을 안내하고, 사용자가 마치면 재실행한다(멱등).

### 5.5 플러그인 리로드 (필수)

사용자에게 `/reload-plugins` 실행을 요청하고 완료를 기다린다(슬래시 명령은
사용자만 실행할 수 있다). 방금 설치한 플러그인의 스킬은 실행 중인 세션에
자동 반영되지 않으므로, 이 단계를 건너뛰면 6단계가
`Error: Unknown skill: multi-agent-starter:configure-multiagent` 로 막힌다.

### 6. 멀티에이전트 시스템 설치 + 디스코드 층

먼저 multi-agent-starter 플러그인의 `configure-multiagent` 스킬을 설치 루트
(2단계에서 정한 폴더)에 대해 flavor `claude`로 실행해 오케스트레이션 뼈대를
얹는다. 완료되면 디스코드 운영 레이어를 오버레이한다:

```
python3 <이 스킬 폴더>/generator/harnessctl.py install --work-dir <설치 루트> --phase overlay
```

### 7. pair

```
python3 <이 스킬 폴더>/generator/harnessctl.py pair \
  --work-dir <설치 루트> \
  --work-channel-id <작업 채널 ID> \
  --chat-channel-id <수다 채널 ID> \
  --approver-user-id <내 사용자 ID>
```

대시보드를 설치하기로 했으면 `--webhook-url-file <설치 루트>/.webhook-url`을
추가한다. 이미 페어링돼 있으면 엔진이 거부한다(덮으려면 `--force`). 완료 후
엔진 출력으로 `.bot-token-*` 파일 4개가 삭제됐는지 확인한다.

### 8. install

```
python3 <이 스킬 폴더>/generator/harnessctl.py install --work-dir <설치 루트> --phase delegate
```

2단계 답에 따라 `--dashboard`(대시보드 예였으면) · `--autostart`(부팅 자동
기동 예였으면)를 붙인다. 코덱스/제미나이 브리지 환경 조립 + 위임 설치
스크립트(`codex-discord`·`usage-coach`·`install-autostart.sh`) 호출까지
이 단계에서 끝난다. Windows에서는 브리지·대시보드가 2차 범위라 `[SKIP]`으로
표시된다(정상 — 오케스트레이터·수다 클로드 두 봇만 이 슬라이스 대상).
`--autostart`는 Windows에서 schtasks 등록만 하고(ADR-0002, onlogon은 다음
로그온부터 적용) **지금 당장 기동하지 않는다** — 9단계에서 두 봇 모두 수동
기동이 필요하다.

### 9. verify + 마무리

봇 기동 전에 설치 루트에서 MCP 연결을 한 번 예열한다. 하네스는 토큰을
전역 경로가 아닌 봇별 상태 폴더에 두므로 **`DISCORD_STATE_DIR`를 반드시
지정한다** — 없이 돌리면 토큰을 못 찾아 항상 실패한다(실측 2026-08-10,
과거 "예열 불안정"의 실체):

macOS/Linux:
```
cd <설치 루트> && DISCORD_STATE_DIR=<설치 루트>/.discord-state claude mcp list
cd <설치 루트> && DISCORD_STATE_DIR=<설치 루트>/chat/.discord-state claude mcp list
```

Windows(pwsh — `$env:`는 그 프로세스 안에서만 유효, 세션별로 따로 실행):
```
cd <설치 루트>; $env:DISCORD_STATE_DIR="<설치 루트>\.discord-state"; claude mcp list
cd <설치 루트>\chat; $env:DISCORD_STATE_DIR="<설치 루트>\chat\.discord-state"; claude mcp list
```

각각 `plugin:discord:discord`가 `✔ Connected`로 뜨는지 확인한다. 환경변수를
지정했는데도 실패하면 **같은 Claude 계정에 동명 세션이 살아 있는지**(이 머신
포함 다른 기기의 `-n orchestrator`/`-n chat-claude`, Windows는 호스트 접미사
포함 세션명 — 활성 이름 충돌은 채널 연결이 로그 없이 스킵된다, 실측
2026-08-10) 또는 유령 리스(강제 종료 후 ~90분)를 의심한다. verify FAIL 시
아래 폴백 절차(재기동 1회 → 예열 복구 → 진단)를 따르면 수렴한다.

verify 전에 수다 클로드를 지금 기동해야 한다.

macOS/Linux: 8단계에서 자동 기동을 켠 경우(`--autostart`) 오케스트레이터는
`install-autostart.sh`가 즉시 띄우지만, 수다 클로드는 plist 파일만 생성되고
지금 당장 뜨지는 않는다(재부팅 후에는 자동 기동). 다음 명령으로 지금
기동한다:

```
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.discord-harness.chat-claude.plist
```

자동 기동을 끈 경우에는 오케스트레이터·수다 클로드 둘 다 수동으로 기동한다:

```
tmux new-session -d -s orchestrator '/bin/zsh -lc "cd <설치 루트>; export DISCORD_STATE_DIR=<설치 루트>/.discord-state; exec scripts/bot-up.sh -n orchestrator --remote-control orchestrator --channels plugin:discord@claude-plugins-official"'
tmux new-session -d -s chat-claude '/bin/zsh -lc "cd <설치 루트>/chat; export DISCORD_STATE_DIR=<설치 루트>/chat/.discord-state; exec <설치 루트>/scripts/bot-up.sh -n chat-claude --remote-control chat-claude --channels plugin:discord@claude-plugins-official"'
```

Windows: 봇을 기동하기 전에 설치 루트가 **orca에 레포로 등록돼 있어야 한다**
(ADR-0005는 "설치기가 한다"로 결정했지만 harnessctl.py·bot_win.py 어디에도
아직 안 배선돼 있다 — 2026-08-29 실측으로 발견한 구멍, 지금은 수동으로 채운다):
```
orca repo add --path <설치 루트>
```
(`chat/`은 별도 등록 불필요 — bot_win.py는 터미널을 항상 설치 루트 기준으로
열고 `chat/`으로는 내부적으로 `cd`한다.) 8단계 `--autostart`는 schtasks
onlogon만 등록하고 지금은 아무 것도 띄우지 않는다(다음 로그온부터 적용,
ADR-0002) — 자동 기동 켬/끔과 무관하게 **두 봇 모두 지금 수동으로 기동해야
한다.** `bots.json`이 기동 정본이라 이름만 넘기면 된다(락 직렬화·감시자는
`up`이 내부 처리):
```
python <설치 루트>\scripts\bot_win.py restart orchestrator
python <설치 루트>\scripts\bot_win.py restart chat-claude
```
출력의 `터미널 term_...` 핸들을 받아 적는다. **최초 기동은 Claude Code
워크스페이스 신뢰 프롬프트에 막힌다.** 실측(2026-08-29, E2E)에선 `wait
--for tui-idle`에 `blockedReason` 필드가 안 잡혔다 — `terminal read`로 화면을
직접 확인해야 한다. **기본 선택지가 `❯ No, exit`이라 빈 텍스트+Enter만 치면
그대로 종료된다** — 위 화살표로 `Yes, I trust this folder`로 이동한 뒤 Enter:
```
orca terminal read --terminal <핸들>
```
`Accessing workspace` / `❯ No, exit` 문구가 보이면:
```
orca terminal send --terminal <핸들> --text $'\x1b[A'
orca terminal read --terminal <핸들>
```
(`❯ Yes, I trust this folder`로 바뀐 것을 확인한 뒤)
```
orca terminal send --terminal <핸들> --text "" --enter
```
두 봇 각각(오케스트레이터·수다 클로드) 반복한다. 이미 신뢰한 폴더는 재기동 시
프롬프트가 안 뜬다.

```
python3 <이 스킬 폴더>/generator/harnessctl.py verify --work-dir <설치 루트> --wait 600
```

`--wait 600`은 필수다 — bot-up.sh(Windows는 `bot_win.py up`)가 봇 기동을
직렬화하므로(락 대기 최대 300초 + 연결 판정 240초) 기동 직후 바로 판정하면
항상 조기 FAIL이 난다.

결과를 그대로 보고한다. "코덱스 TUI" FAIL이면(세션 없음 또는 pane에 codex
없음 — codex TUI는 죽어도 자동 재기동되지 않는다) 멱등 스크립트로 재기동
후 verify를 다시 돌린다(macOS/Linux 전용 — Windows는 코덱스 브리지가 2차
범위라 verify가 이 항목을 FAIL이 아닌 `[SKIP]`으로 낸다, 이 폴백은 해당
없음):

```
bash <repos>/codex-discord/scripts/tui-up.sh
```

오케스트레이터/수다 클로드가 "MCP 미기동" 또는
"서버 프로세스 없음" FAIL이면(첫 기동 경합으로 MCP 서버가 아예 안 뜨는
경우가 실측됨) 해당 세션을 재기동하고 verify를 다시 돌린다 — **단 1회만**.
macOS/Linux:
```
bash <설치 루트>/scripts/bot-restart.sh orchestrator   # 또는 chat-claude
python3 <이 스킬 폴더>/generator/harnessctl.py verify --work-dir <설치 루트> --wait 600
```
Windows:
```
python <설치 루트>\scripts\bot_win.py restart orchestrator   # 또는 chat-claude
python3 <이 스킬 폴더>/generator/harnessctl.py verify --work-dir <설치 루트> --wait 600
```

재기동 후에도 같은 FAIL이면 **재기동을 반복하지 않는다**(수렴하지 않는
경우가 실측됨 — 2026-08-05). 다음은 예열 복구 1회 — 실측에서 유일하게
상태를 푼 경로다. macOS/Linux:
```
# 상태 폴더는 세션별: orchestrator → <설치 루트>/.discord-state, chat-claude → <설치 루트>/chat/.discord-state
cd <설치 루트> && DISCORD_STATE_DIR=<세션별 상태 폴더> claude mcp list   # discord ✔ Connected 확인
bash <설치 루트>/scripts/bot-restart.sh <세션>
python3 <이 스킬 폴더>/generator/harnessctl.py verify --work-dir <설치 루트> --wait 600
```
Windows(pwsh):
```
cd <세션별 폴더>; $env:DISCORD_STATE_DIR="<세션별 상태 폴더>"; claude mcp list   # discord ✔ Connected 확인
python <설치 루트>\scripts\bot_win.py restart <세션>
python3 <이 스킬 폴더>/generator/harnessctl.py verify --work-dir <설치 루트> --wait 600
```

예열 복구로도 같은 FAIL이면 **동명 세션 충돌부터 확인한다**.

macOS/Linux: 이 머신에서 `ps aux | grep -o '\-n [a-z-]*'`로 같은 이름
(`orchestrator`·`chat-claude`)의 다른 클로드 세션이 살아 있으면 그 세션을
`/exit`로 내린 뒤 bot-restart — 같은 Claude 계정의 다른 기기에 하네스를 또
설치한 경우가 여기 해당한다.

Windows(pwsh): `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine
-match '-n (orchestrator|chat-claude)' } | Select-Object ProcessId,CommandLine`
로 확인한다. 살아 있으면 해당 세션의 orca 터미널에 `/exit`를 보낸 뒤
bot_win.py restart:
```
orca terminal send --terminal <핸들> --text "/exit" --enter
```
**Git Bash에서 이 명령을 직접 칠 때는 `MSYS_NO_PATHCONV=1`을 앞에 붙인다**
— 안 붙이면 MSYS가 `/exit`를 `C:/Program Files/Git/exit` 같은 경로로
오변환한다(실측, 구현 함정 ③). pwsh에서 실행하면 이 문제가 없다.

그래도 같은 FAIL이면 진단 증거를 수집해 보고하고 멈춘다:

1. 프로세스 부재 확인. macOS/Linux: `ps -axo pid,ppid,command | grep -E
   "bun run.*discord" | grep -v grep`. Windows: `Get-CimInstance Win32_Process
   | Where-Object { $_.CommandLine -match "bun run.*discord" }` — 봇 세션
   자손에 서버 프로세스가 없으면 spawn 자체가 실패하는 상태다.
2. spawn 오류 캡처(macOS/Linux 전용 진단 — Windows 캐시 경로는
   `%USERPROFILE%\.claude\plugins\cache\...`로 동형이나 이 편집 절차는
   2차 범위): 플러그인 캐시(`~/.claude/plugins/cache/claude-plugins-official/discord/<버전>/.mcp.json`)의
   `args`를 임시로 `["-c", "exec bun run --cwd <같은 캐시 경로> --shell=bun --silent start 2>>/tmp/discord-mcp-spawn.err"]`,
   `command`를 `"bash"`로 바꾸고 bot-restart 1회 → `/tmp/discord-mcp-spawn.err`
   내용 확인 → **파일을 원복**한다.
3. 위 증거를 사용자에게 보고한다. 이 증상(플러그인 로드 O·환경 O·수동 실행
   O인데 봇 세션에서만 spawn 실패)은 Claude Code 채널 모드 내부 문제로,
   설치기 범위 밖이다.

이어서 마무리 안내:

- **실제 응답 확인(자동화 불가)** — 디스코드 작업 채널에서 오케스트레이터
  봇에게, 수다 채널에서 클로드 봇에게 직접 인사해 응답이 오는지 확인해
  달라고 요청한다.
- **코덱스·제미나이 호명 규칙** — 수다 채널에서 브리지 봇은
  ①메시지가 봇 이름으로 **시작**하거나("코덱스야 …") ②봇을 @멘션할 때만
  반응한다. 이름이 문장 중간에 있으면 반응하지 않는 게 정상이다.
  코덱스는 tmux 세션 `codex-live`의 TUI로 돌아가므로 작업 과정을
  `tmux attach -t codex-live`로 볼 수 있다(Windows는 브리지가 2차 범위라
  해당 없음).
- **재시작 리추얼** — 컨텍스트가 차면 채널에서 "세션 마감하고 재시작해" →
  macOS/Linux `scripts/bot-restart.sh <세션>` / Windows
  `python <설치 루트>\scripts\bot_win.py restart <세션>` → "이어서하자".
- **폴더 봇 추가(선택)** — 다른 작업 폴더도 디스코드 채널 봇으로 만들고
  싶으면 folder-bot 스킬("이 폴더를 디스코드 봇으로 만들어줘")을 안내한다.
- **상시 점검**: `python3 <이 스킬 폴더>/generator/harnessctl.py doctor`
- **제거**: `python3 <이 스킬 폴더>/generator/harnessctl.py remove`

## 제거

"하네스 제거해줘" 요청을 받으면:

```
python3 <이 스킬 폴더>/generator/harnessctl.py remove --work-dir <설치 루트>
```

엔진이 tmux 세션·plist·위임 설치분(브리지·대시보드)·오버레이 파일(해시 일치
분만)·CLAUDE.md 마커 블록·`.mcp.json` 추가 항목·봇 권한 사전 승인
(`settings.local.json` 추가분)·소스 저장소를 제거한다. 일부 항목이 `[WARN]`
으로 남으면 상태 파일을 보존하고 재실행 시 이어서 제거한다.
**보존되는 것**을 그대로 안내한다: `.env` · `.discord-state` · `chat/`(사용자
수정분) · `tasks/` · `SESSION.md` · `~/.config/usage-coach/`. 사용자가 수정한
오버레이 파일은 해시 불일치로 자동 보존되며 엔진이 `[WARN]`으로 표시한다.
starter·folder-bot 플러그인과 그 산출물은 remove 범위 밖이다 — 멀티에이전트
구성 제거는 multi-agent-starter 스킬로, 폴더 봇 제거는 folder-bot 스킬의
`botctl.py remove`로 각각 안내만 한다.

## 점검

"하네스 점검해줘" 요청을 받으면:

```
python3 <이 스킬 폴더>/generator/harnessctl.py doctor
```

읽기 전용 — 3레포 fetch 기록·검증 조합 핀 일치 여부, 플러그인(multi-agent-
starter·folder-bot) 설치 버전과 호환 최소 버전, 위임 계약 파일(브리지·대시보드
·오토스타트 스크립트) 존재·실행권한, 오버레이 manifest 스키마 버전, 페어링
(`.env`) 여부, plist 2종, tmux 세션 2종(orchestrator·chat-claude) 생존을
대조 보고한다. 각 `[WARN]`/`[FAIL]` 항목은 엔진 메시지를 그대로 옮기고 다음
행동을 덧붙여 해설한다(예: "fetch 기록 없음 → harnessctl.py fetch 필요").
