# Windows 지원 선행 스파이크 결과 (2026-08-27)

계획서 `~/.claude/plans/glistening-leaping-valiant.md`의 S1~S3 실측. 머신: Windows 11 Pro
26200, python 3.13.0, Orca 런타임 ready, tmux 없음.

## S2 — MCP 로그 경로 · 맹글링 규칙 (확정)

Windows 경로는 `%LOCALAPPDATA%\claude-cli-nodejs\`**`Cache`**`\<맹글링>\mcp-logs-<서버>\`.
macOS(`~/Library/Caches/claude-cli-nodejs/<맹글링>/`)보다 `Cache` 세그먼트가 하나 더 있다.

맹글링 규칙은 **`re.sub(r'[\\/:.]', '-', path)`**로 확정(`:`·`\`·`.` 셋 다 `-`). 실측:

```
C:\Users\hdmun\AppData\Local\Temp\claude\…\scratchpad\spike.s2\sub.dir
→ C--Users-hdmun-AppData-Local-Temp-claude-…-scratchpad-spike-s2-sub-dir
```

`:`·`\`·`.` 셋 다 `-`로 바뀌고 기존 하이픈은 보존된다. macOS의 `[/.]`에 `\`와 `:`가 더해진
형태다. 규칙이 확정됐으므로 계획서에 적었던 glob 폴백은 불필요하다.

### 부수 확인 — discord 플러그인 MCP는 Windows에서 동작한다

같은 실측에서 `plugin:discord:discord`가 `CONNECTION_CLOSED`로 실패했으나 로그를 보면
원인은 토큰 부재다:

```
Server stderr: discord channel: DISCORD_BOT_TOKEN required
  set in C:\Users\hdmun\.claude\channels\discord\.env
```

즉 `bun run --cwd …/discord/0.0.4 … start` 런처가 Windows에서 정상 기동해 stderr까지 냈다.
플러그인 MCP 서버 본체는 Windows 호환이다. 기본 토큰 경로가 전역
(`~/.claude/channels/discord/.env`)이므로 `DISCORD_STATE_DIR` 주입이 Windows에서도 필요하다.

## S3 — orca repo add · terminal create (성공)

원격이 없는 순수 로컬 git 레포도 등록된다. `orca repo add --path` 결과가 `kind: "git"`,
`upstream: null`이고 worktree의 `projectId`가 `repo:<id>`로 잡힌다(GitHub 레포는
`github:<owner>/<name>`). **GitHub 원격은 전제가 아니다.**

`orca terminal create --worktree "path:<루트>" --title <이름> --command <명령>` 성공.
`hostPlatform: "win32"`, 셸은 **PowerShell**이며 `--command`에 `cd chat`을 넣어 하위 폴더에서
기동할 수 있음을 확인했다 — 수다 클로드를 `<루트>/chat`에서 띄우는 경로가 확보된다.

### 미해결 — `orca repo` 에 제거 명령이 없다

`repo list | add | show | set-base-ref | search-refs`가 전부다. **CLI로 등록 해제가 불가능**
하므로 계획서 결정 8의 "state에 기록해 remove가 회수한다"는 성립하지 않는다. 선택지는
①remove가 등록분을 그대로 남기고 사용자에게 안내만 ②Orca UI에서의 수동 제거를 문서화
③등록 자체를 하지 않고 사용자가 이미 등록한 레포만 대상으로 삼기(preflight가 확인).
이 스파이크 자체도 `harness-spike` 레포를 사용자 Orca에 남겼다(스크래치패드 경로라 곧 사라짐).

**결론(2026-08-27): ①로 확정** — 설치기가 등록하고 `remove`는 안내만 한다. `cmd_plugins`의
마켓플레이스·플러그인 등록을 remove가 되돌리지 않는 선례와 성격이 같고, diff 0은 작업 폴더 안
설치기 소유분 기준이다. ADR-0005 참조.

## S1 — orca terminal 생명주기 (부분 성공)

### ③ `/exit` 주입 — 검증 완료

`orca terminal send --terminal <handle> --text "/exit" --enter`로 claude가 정상 종료했다
(`Resume this session with: claude --resume "spike-w1"` 출력 후 프로세스 소멸 확인).
세션 호스트 결정(ADR-0001)의 핵심 근거가 실증됐다.

`orca terminal wait --for tui-idle`도 동작한다. 첫 기동 시 신뢰 프롬프트에 막히면
`satisfied: false`와 함께 `blockedReason: "codex-trust-workspace"`를 돌려준다 — 무인 봇에
쓸 수 있는 진단 신호다. 빈 텍스트 + `--enter`로 프롬프트를 통과시킨 뒤 idle에 도달했다.

**구현 노트**: `wait --for exit`는 **셸** 종료를 기다린다. claude만 죽고 pwsh 프롬프트가
남으면 timeout이 난다. 봇 종료 판정은 프로세스 테이블로 해야 한다.

### ① 헤드리스 동작 — 가능. `serve`는 창 없는 앱이다

첫 시도에서 앱이 떠 있는 채로 `orca serve --port 7391`이 exit 3으로 거부됐다:

```
[single-instance] Another Orca instance is already running for this userData profile
```

앱을 내린 뒤 재시도하니 기동했고, **`serve`가 만든 프로세스가 그냥 `Orca.exe`였다**
(pid 37792, Electron). 즉 별도 경량 서버가 아니라 **같은 앱을 창 없이 띄우는 모드**다.
단일 인스턴스 락에 걸렸던 이유가 이것이다.

결정적으로, 그 상태에서 `orca open`을 실행하니 **충돌 없이 그 런타임에 창이 붙었다** —
`desktopWindowStatus`가 `openable → available`로 바뀌고 `runtimeId`(`a3ed2685-…`)는 동일하게
유지됐다. 재시작도 상태 손실도 없다.

따라서 "`serve`냐 앱이냐"는 배타 선택이 **아니다**. 같은 앱이고 창이 선택 사항이다:

- 로그온 시 `orca serve`로 창 없이 기동 → 사용자를 방해하지 않는다
- 사용자가 나중에 `orca open`으로 창을 붙일 수 있다 (기존 런타임 재사용)
- 이미 앱이 떠 있으면 `serve`는 exit 3 — 부트스트랩은 이 코드를 "이미 기동됨"으로 취급하면 된다

기동 시 `[claude-live-pty] Seeded 2 persisted Claude session id(s) into the refresh gate`가
찍히며 살아남은 claude 세션을 그대로 인계받는다.

### ② 앱 종료 시 터미널 생존 — 생존한다 (직접 실증)

사용자가 `Orca.exe`를 직접 종료한 뒤 확인했다. `Orca.exe`는 전부 사라졌지만
`orca-terminal-daemon.exe`(17864)와 그 자손 `pwsh`→`claude` 4개가 전부 생존했다.
데몬 시작은 2026-08-24 15:17, 종료된 앱 인스턴스는 2026-08-26 23:42 — 데몬이 앱 재시작을
이미 한 번 이상 살아남은 상태였다. **ADR-0001의 최대 잔여 리스크가 해소됐다.**

### 앱이 내려간 동안의 제어 계층

봇은 살지만 **관리는 불가능하다**:

```
$ orca terminal list --json
{"ok": false, "error": {"code": "runtime_unavailable",
 "message": "Could not read Orca runtime metadata at
             C:\Users\hdmun\AppData\Roaming\orca\orca-runtime.json. Start the Orca app first."}}
```

런타임(창 유무 무관)을 다시 띄우면 제어가 복구되고, **헤드리스에서 제어 계층이 전부
동작한다**: `list`·`show`·`read`·`create`·`send` 실측 통과(`HEADLESS-CREATE-OK`·
`HEADLESS-SEND-OK`). pty 버퍼는 데몬이 갖고 있어 `read`가 화면 내용을 그대로 돌려준다.

즉 **완전 무인 운영이 성립한다** — 데스크톱 창이 한 번도 열리지 않아도 봇을 만들고,
입력을 주입하고, 화면을 읽을 수 있다.

### 식별자 — title은 런타임 재시작을 못 넘긴다

헤드리스 런타임에서 기존 터미널 2개의 렌더러 측 메타가 전부 비었다:
`title: null`, `lastOutputAt: null`, `preview: ""`, `paneRuntimeId: -1`. 앱 세션에서는
`"✳ Claude code antigravity Codex 워크플로우 파이프라인"`처럼 채워져 있던 값이다.

반면 `--title`을 명시해 헤드리스에서 새로 만든 터미널은 `'spike-headless'`가 그대로 조회됐다.
이후 창 있는 앱으로 되띄우자 두 터미널의 title이 그대로 복원됐다. 즉 title은 **영구 소실이
아니라 렌더러가 있어야 채워지는 값**이다. 그런데 부트스트랩과 재기동은 헤드리스에서 도므로,
정작 필요한 시점에 `null`이다.

살아남는 필드: `handle`·`ptyId`(`<repoId>::<path>@@<8hex>`)·`worktreeId`·`worktreePath`·
`connected`·`writable`.

계획서의 "식별은 `title` + `worktreePath`"는 그대로 쓸 수 없다. 봇 2개가 worktree 1개를
공유하므로 `worktreePath`만으로도 부족하다. 대안은 `bots.json`에 생성 시점의 `ptyId`를
기록하고, 그것이 어긋나면 프로세스 테이블에서 `-n <세션명>`으로 재확인하는 이중 경로다.

## 프로세스 판정 (결정 5) — 검증 완료

`pwsh -NoProfile Get-CimInstance Win32_Process`가 `ProcessId`·`ParentProcessId`·`CommandLine`
3필드를 주고 338프로세스 열거에 0.64초.

- 커맨드라인에서 `-n spike-w1`로 뿌리 특정 성공(ROOT COUNT 1), 자손 트리 워크 동작.
- **MCP stdio 서버는 `claude.exe`의 직계 자식으로 뜬다**(`sleeper pid=35488 ppid=19380`,
  부모가 `claude.exe`). `mcp_server_alive`의 트리 판정이 Windows에서 성립한다.
- `os.kill(pid, 0)`은 죽은 pid에도 정상 반환한다(py3.13 실측). 생존 판정에 쓸 수 없다.

### 함정 — 커맨드라인 매칭은 자기 자신을 제외해야 한다

실측 중 `-like '*setInterval*3600000*'` 필터가 **그 문자열을 담은 pwsh 자신**을 매칭해
스스로를 죽였다(exit 255). macOS의 `grep -v grep` 관용구와 같은 문제이며, `-n orchestrator`를
찾는 판정 코드에서 똑같이 재현된다. self와 조상 프로세스를 반드시 제외한다.

## Git Bash 경유 함정 — MSYS 경로 변환

Git Bash에서 `orca terminal send --text "/exit"`를 실행하면 MSYS가 `/exit`를 POSIX 경로로
오인해 `C:/Program Files/Git/exit`로 변환해 보낸다(claude가 "stray shell path"로 응답한 것을
실측). `MSYS_NO_PATHCONV=1`을 붙이거나 pwsh에서 실행해야 한다. python `subprocess`로 호출하면
변환이 없어 안전하므로 `bot_win.py` 경로는 영향받지 않지만, **SKILL.md의 수동 절차 안내에서
반드시 걸린다**.

## 계획 반영 사항

1. 맹글링 glob 폴백 삭제 — 규칙 확정.
2. 결정 8 확정 — 설치기가 등록하고 remove는 안내만(ADR-0005). 등록 해제 CLI 부재.
3. `_process_table()` 구현에 self/조상 제외 필수.
4. 봇 종료 판정에 `wait --for exit` 사용 금지 — 프로세스 테이블로.
5. SKILL.md Windows 절에 `MSYS_NO_PATHCONV=1` 주의 삽입.
6. 첫 기동 신뢰 프롬프트 통과를 설치 절차에 명시(무인 봇 전제 조건).
7. 자동 기동 부트스트랩은 `orca serve`(창 없는 기동)를 쓰고 exit 3을 "이미 기동됨"으로
   취급한다. 사용자는 필요할 때 `orca open`으로 같은 런타임에 창을 붙인다.
8. `bot_win.py restart`는 런타임 가용을 선행 조건으로 갖는다 — 내려가 있으면 `orca serve`로
   먼저 띄우고 대기해야 한다. 봇 생존 자체는 데몬이 보장하므로 재기동만 막힌다.
9. 터미널 식별을 title에 의존하지 않는다 — `bots.json`에 `ptyId` 기록 + 프로세스 테이블
   `-n <세션명>` 대조의 이중 경로로 간다.
