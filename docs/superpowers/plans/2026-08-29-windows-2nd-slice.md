# Windows 2차 슬라이스 — 재정박 + 미지원 4건

## Context

Windows 1차 슬라이스(오케스트레이터 + 수다 클로드 코어)는 2026-08-29 E2E 완주했다.
남은 것을 정리하려 감사한 결과, **두 가지 전제가 무너졌고 미지원 항목이 하나 늘었다.**

1. **netwaif 푸시 권한 없음.** `gh api repos/netwaif/discord-multiagent` → `push: false, pull: true`.
   `hdmun/discord-harness-installer`는 netwaif 포크(8/28), `hdmun/usage-coach`도 포크.
   `discord-multiagent` 로컬 클론은 origin=netwaif이고 **ahead 6** — 푸시할 수 없다.
   즉 SESSION.md `-2`("netwaif에 태그 push")는 **실행 불가능한 항목**이다.
2. **mac 수급 무기한.** SESSION.md `-2.5`(macOS 회귀 확인)를 원래 게이트대로 두면
   Windows 작업 전체가 무기한 동결된다.
3. **folder-bot 플러그인이 macOS 전용이었다(신규 발견).** `botctl.py`에 플랫폼 분기가
   **0개**다 — `:91` `sys.exit("tmux를 찾을 수 없음 — brew install tmux")`,
   `:109` `~/Library/LaunchAgents/com.folder-bot.*.plist`, `:122` plist가 `tmux new-session` 실행.
   그런데 `harnessctl.py`의 `PLUGINS`가 이걸 `claude plugin install`로 **깔아준다** —
   설치기가 Windows에서 안 도는 도구를 말없이 설치해 주는 상태다.

이 플랜은 (1)(2)에 대한 재정박이고, 그 위에서 미지원 4건을 순서대로 푼다.

**의존물 감사 결과 (전수):**

| 의존물 | Windows | 근거 |
|---|---|---|
| `discord-multiagent` | ✅ 포팅됨 | `scripts/bot_win.py` (529행, E2E 검증) |
| `folder-bot` 플러그인 | ❌ **신규 발견** | `botctl.py` 플랫폼 분기 0, macOS 전용 표면 52줄 |
| `codex-discord` | ❌ | `install.sh:14` uname 게이트, `src/tmux.mjs` 6개 호출 |
| `usage-coach` | 🔄 다른 세션 포팅 중 | `codexbar` Windows 빌드 없음(macOS + Linux 타르볼만) |
| `multi-agent-starter` | ⚠️ Git Bash 필요 | `.sh` 3개(`call_worker.sh`·`gemini_api.sh`·`check-invariants.sh`) |
| codex·agy·node·orca·git·pwsh | ✅ 네이티브 | 이 머신 실측 |
| tmux·launchd | ❌ 대체됨 | orca terminal(ADR-0001) + schtasks(ADR-0002) |

---

## 확정 결정 (2026-08-29 그릴링)

1. **상류 3레포 + folder-bot 전부 hdmun 포크.** netwaif PR 대기 안 함.
2. **소유자 해석 = `pins.json`에 owner 필드.** `repo_url()`은 범용 유지,
   `HARNESS_REPO_BASE`는 테스트 시임으로 손대지 않는다. 소유자가 **섞이므로**
   (`netwaif/multi-agent-starter` 유지 + `hdmun/{나머지 4개}`) 항목별 owner,
   미지정 시 `netwaif` 폴백.
3. **기존 클론 마이그레이션 = fetch가 origin URL 대조 후 자동 정정.**
   `cmd_fetch:174-180`은 `dst.exists()`면 origin을 재확인하지 않아, owner만 바꾸면
   기존 환경(이 머신 포함, `~/.local/share/discord-harness/repos/*` 전부 netwaif origin)에서
   **조용히 무효**가 된다.
4. **macOS 게이트 범위 축소.** 포크 push·태그·2차 슬라이스는 게이트 없이 진행.
   "내 macOS 기기에 새 pins를 설치하는 순간"만 회귀 확인 게이트를 건다.
   근거(코드 실측): `_cmd_argv:759-760`의 macOS 분기는 `cmdline.split()`으로 **종전과 동일**,
   `bot_sessions`/`default_session_name:291`은 macOS 기본명을 유지해 **판정 결과 동일**,
   유일한 진짜 변경 `pid_alive:689`(os.kill → ps 스캔)는 **호출부 1곳**(`:1059` verify의
   브리지 데몬 생존)뿐이라 최악이 리포트 한 줄 오판이다. discord-multiagent 미푸시
   6커밋은 **772 insertions / 0 deletions**, macOS `.sh` 전부 무수정.
5. **착수 순서 = ④folder-bot → ①브리지 → ③TUI.** folder-bot이 새 배관(포크·owner·
   origin 정정·마켓플레이스 재등록)의 파일럿이다. `bot_win.py`가 똑같은 문제를 이미
   Windows E2E로 풀어둬서 미지가 적고, 미검증 배관을 637행짜리에서 먼저 굴린 뒤
   ①에 건다.
6. **folder-bot 포팅 범위 = claude 엔진만.** codex 엔진(`write_codex_plists:214`)은
   ①과 같은 뿌리(codex TUI를 orca 터미널에)라 ①에 묶는다. Windows에서
   `--engine codex`는 명시적 거부 + 사유 출력.
7. **마켓플레이스 이름 유지 + source.repo 대조 후 재등록.** `known_marketplaces.json`은
   이름을 키로 쓰고(`"folder-bot"` → `netwaif/folder-bot`), 포크도 `name: "folder-bot"`이라
   충돌한다. 결정 3(fetch origin 자동정정)과 동형으로 처리한다.
8. **Windows 진입점 규약 = `<이름>_win.py` 별도 파일.** macOS 정본 파일을 한 줄도 안 건드려
   회귀 위험을 0으로 만든다(mac 없는 지금 결정적). `bot_win.py` 전례 승계, 중복 로직은
   ADR-0004(계약 테스트로 봉인) 방식으로 감수.
9. **② 계약 = 분리 고정.** 웹훅 verify는 지금 켜고(코드 무수정), 주기 실행만 위임.
   `harnessctl.py:1087-1102`의 웹훅 판정은 **플랫폼 의존이 하나도 없다** —
   `home()/".config/usage-coach/discord.json"` 읽고 `urllib`로 POST가 전부인데
   `:1085`의 `IS_WIN`이 막고 있었다.

---

## Phase 0 — 배관 (파일럿 선행)

**Files:** `plugins/harness-installer/skills/configure-harness/generator/{harnessctl.py,pins.json}`,
`docs/adr/0002-schtasks-for-autostart.md`, `plugins/harness-installer/skills/configure-harness/SKILL.md`,
`tests/test_harnessctl.py`, `SESSION.md`

- [ ] **P0-1 ADR-0002 정정** — `docs/adr/0002-schtasks-for-autostart.md:7`의
  "관리자 권한이 필요 없으며"는 **틀렸다**. 일반 계정 `schtasks /create /sc onlogon`
  Access Denied, 관리자 pwsh 성공(8/28 발견, 8/29 재확인). 본문 정정 + `## 2026-08-29`
  절 추가. SKILL.md의 자동 기동 단계에도 관리자 pwsh 요구를 명시.
  **먼저 할 것** — ④①이 둘 다 schtasks 등록을 늘리므로 틀린 전제가 세 곳에 복제된다.
- [ ] **P0-2 pins.json owner (schema_version 2)** — `repos`/`plugins` 항목을
  `{"ref": "v0.2.0", "owner": "hdmun"}` 형태로 확장, owner 미지정 시 `netwaif` 폴백.
  `repo_url(name)`(`:55`)이 pins의 owner를 읽도록 변경(시그니처 유지,
  `HARNESS_REPO_BASE` 우선순위는 그대로 — 테스트 시임 보존).
  `PLUGINS`(`:27`)의 하드코딩 `netwaif/...`도 pins에서 읽도록.
  `cmd_doctor`의 `pins()["repos"][name]` 소비부(`:842`)가 dict로 바뀌는 것에 유의.
- [ ] **P0-3 fetch origin 자동 정정** — `cmd_fetch`(`:169`)의 `else` 가지에서
  `git remote get-url origin`을 기대값과 비교, 다르면 `git remote set-url origin` 후
  한 줄 출력. 사용자가 따로 추가한 remote(`local-dev` 등)는 건드리지 않는다.
- [ ] **P0-4 마켓플레이스 재등록** — `plugin_cmds(host)`(`:200`)가 소유자 불일치를
  감지해 `marketplace remove <name>` → `add <owner>/<name>` 순으로 내도록.
  **구현 전 실측 필요:** `claude plugin marketplace add`가 같은 이름 다른 repo를
  덮어쓰는지 거부하는지 미확인 — 덮어쓴다면 remove 단계 생략 가능.
- [ ] **P0-5 preflight에 bash 추가** — `cmd_preflight`(`:123-131`)의 Windows 도구 목록에
  `bash`가 **없다**. `cmd_remove:928`이 `bash_bin()`으로 상류 `uninstall.sh`를 돌리고
  multi-agent-starter의 `.sh` 3개도 bash를 요구한다. `("bash", "FAIL", "Git for Windows 동봉")`
  추가 — `bash_bin():85-89`이 이미 WSL 스텁 회피 로직을 갖고 있으니 그 경로를 그대로 쓴다.
- [ ] **P0-6 bots.json remove 미회수 버그** — `write_bots_json:305`가 만든
  `<work>/bots.json`이 `st["overlay"]`에 등록되지 않아 `cmd_remove`(`:932-940` 회수 루프)가
  건너뛴다. "remove 후 작업 폴더 diff 0" 계약 위반. 플랫폼 무관.
  `write_bots_json`이 state에 sha256을 등록하게 하고(오버레이 항목과 동형),
  `p.write_text`에 `newline=""` 추가(8/29 CRLF 사고 규약).
- [ ] **P0-7 SESSION.md 재정박** — `-2`를 "netwaif에 태그 push"에서 hdmun 포크 경로로 교체,
  `-2.5`를 결정 4의 축소된 게이트로 교체, 이 플랜 파일 경로를 다음 단계에 연결.
  결정 기록에는 **삭제 없이 추가**(netwaif 푸시 권한 부재 판명 + 게이트 축소 사유).
- [ ] **P0-8 4레포 포크 생성** — `gh repo fork netwaif/{discord-multiagent,codex-discord,folder-bot}`
  (usage-coach는 이미 있음). `~/repo/ref/discord-multiagent`의 미푸시 6커밋을 포크로 push.
  **verify:** `harnessctl.py fetch` 재실행 시 origin이 hdmun으로 정정되고 핀 체크아웃 성공.

**Phase 0 검증:** `python -m pytest tests/ -q` 그린(현재 37 passed / 6 skipped 기준),
`harnessctl.py preflight`·`fetch`·`doctor` 3종을 이 머신에서 실행해 owner 경로 확인.

---

## Phase 1 — ④ folder-bot Windows 포팅 (파일럿)

**Files:** `hdmun/folder-bot` 포크 —
`plugins/folder-bot/skills/configure-bot/generator/botctl_win.py`(신설),
`plugins/folder-bot/skills/configure-bot/SKILL.md`(플랫폼 분기),
`.claude-plugin/marketplace.json`(version bump)

`botctl.py`는 637행, 서브커맨드 7개(`add`/`list`/`remove`/`pair`/`start`/`stop`/`doctor`),
정본은 `config_dir()/bots.json`(전역) — 하네스의 `<work>/bots.json`과 **다른 파일·다른 스키마**다.
따라서 `bot_win.py`를 그대로 복사할 수 없고, **헬퍼만 재사용**한다.

**재사용할 기존 코드 (`~/repo/ref/discord-multiagent/scripts/bot_win.py`):**
- `orca_bin`/`orca_json`/`runtime_ready`/`ensure_runtime`(`:220-259`) — orca 런타임 기동·대기
- `worktree_selector`(`:262`) — 터미널은 항상 레포 루트, 봇 폴더는 `cmd_up`이 `os.chdir`
  (8/29 실측 버그 ③의 결론 — 봇 서브폴더는 git worktree가 아니라 `selector_not_found`)
- `orca_terminal_{list,create,send,close}`(`:272-293`)
- `_ps_quote`/`build_up_command`(`:296-311`), `_process_table_win`/`_cmd_argv0`/
  `_session_process_alive`(`:312-357`)
- `pid_alive`(`:111`), `acquire_lock`/`spawn_watcher`/`cmd_watch`(`:132-217`)
- schtasks 등록/해제 경로(`cmd_restart` 이후) — **관리자 권한 필요**(P0-1)

**MCP 로그 경로:** `botctl.py:502`의 `Library/Caches/claude-cli-nodejs`는
`harnessctl.py`의 `mcp_log_dir`/`mangle`(`:167-176` 동형)에 Windows판이 이미 있으니 이식한다.

- [ ] **F1-1 `botctl_win.py` 신설** — claude 엔진 한정으로 `add`/`list`/`remove`/`pair`/
  `start`/`stop`/`doctor` 7개. plist 자리는 schtasks, tmux 자리는 orca terminal.
  `--engine codex`는 명시적 거부 + 사유 출력(결정 6).
- [ ] **F1-2 SKILL.md 플랫폼 분기** — `configure-bot` 스킬이 Windows에서 `botctl_win.py`를
  부르도록. 신뢰 프롬프트 절차는 harness SKILL.md의 8/29 정정본을 승계
  (기본 선택지가 `❯ No, exit`라 **위 화살표로 `Yes, I trust this folder` 이동 후 Enter** —
  "빈 텍스트+Enter"는 틀림).
- [ ] **F1-3 계약 테스트** — ADR-0004 방식. `--dry-run` 명령 문자열 + 재실행 멱등.
- [ ] **F1-4 설치기 배선** — `pins.json`의 `plugins.folder-bot`을 hdmun 소유자·새 버전으로.
  (겸사겸사 기존 이월 항목: pins의 folder-bot이 `0.1.1`인데 실제 최신은 `0.1.5`였다)

**Phase 1 검증:** 이 머신에서 임의 폴더 하나에 `/configure-bot`으로 봇 추가 →
디스코드 실채널 응답 1회 → `stop` → `start` → `remove` 후 폴더 diff 0.

---

## Phase 2 — ① codex-discord 브리지 Windows 지원

**Files:** `hdmun/codex-discord` 포크 —
`scripts/bridge_win.py`(신설), `src/pane.mjs`(신설, `src/tmux.mjs` 대체),
`src/{codex,agy}.mjs`(spawn 수정), `src/index.mjs`(import 경로만)

런타임 의존물은 전부 Windows 네이티브 존재 확인:
`codex` → `%APPDATA%\npm\codex.cmd`, `agy` → `%LOCALAPPDATA%\agy\bin\agy.exe`,
`node` v23.3.0, `orca` → `orca.cmd`/`orca.exe`. **tmux만 없다.**

- [ ] **B2-1 스파이크: 데몬 단독 기동 (게이트)** — `.env`에서 `TUI_PANE`/`TUI_CHANNEL_ID`를
  빼면 `src/tmux.mjs` 경로를 타지 않는다. `node --env-file=.env src/index.mjs`를 손으로
  띄워 `logs/daemon.log`에 `로그인:`이 찍히는지 확인.
  **verify: 디스코드 수다 채널에서 코덱스 호명 1회 응답.**
  실패하면 B2-2 이후 설계가 통째로 달라진다(spawn 계층 문제) — 여기서 멈추고 재설계.
- [ ] **B2-2 `.cmd` spawn 수정** — `src/codex.mjs:53` / `src/agy.mjs:47`의 `spawn(CODEX_BIN, …)`.
  Windows npm 셔임은 `codex.cmd`라 `shell: true` 또는 `cmd /c` 경유가 필요하다
  (이 프로젝트에서 WinError 2/193으로 **3회** 겪은 함정).
- [ ] **B2-3 `src/pane.mjs`** — `tmux.mjs`의 공개 인터페이스
  (`pasteToPane`/`capturePane`/`paneCurrentCommand`/`paneHasCodex`/`extractSessionId`/`UUID_RE`)를
  그대로 유지하고 내부만 `process.platform`으로 tmux/orca 분기.
  **macOS 무변경이 성공 기준** — `src/index.mjs:10`의 호출부를 수정 없이 통과시킨다.
- [ ] **B2-4 `bridge_win.py`** — 서브커맨드 `install`/`up`/`restart`/`tui-up`/
  `autostart-install`/`autostart-remove`/`autostart-boot`. `install`은 plist 3종 대신
  schtasks + `npm install --omit=dev` + 워크스페이스 `AGENTS.md` 시딩
  (`install.sh:47-53`과 동일 동작). KeepAlive 대체는 `bot_win.py`의 `spawn_watcher` 패턴.
  `tui-up`은 `tui-up.sh` 등가물 — orca terminal 생성 → 준비 대기(`terminal read`로
  `›`/`OpenAI Codex` 검출) → 더미 턴 → 롤아웃 대기.
  **함정: 롤아웃 cwd 비교에 문자열 grep 금지.** Windows 롤아웃은
  `"cwd":"C:\\Users\\hdmun"`으로 백슬래시가 JSON 이스케이프된다(실측).
  `harnessctl.py:_rollout_exists:782`가 이미 `json.loads` 후 `payload.cwd` 비교라
  **그 방식을 그대로 승계**한다(`tui-up.sh`의 `grep -qF`는 Windows에서 깨진다).
- [ ] **B2-5 folder-bot codex 엔진** — 결정 6에서 미룬 `write_codex_plists:214` 경로를
  B2-3/B2-4 성과로 마무리. `botctl_win.py`의 `--engine codex` 거부를 해제.
- [ ] **B2-6 설치기 배선** — `harnessctl.py:1117-1118`의 install SKIP 제거,
  `write_bridge_envs(work)`(`:483`) 실행 + `bridge_win.py install` 위임.
  `:1044-1045`의 verify SKIP → 실판정(`judge_bridge:821`은 로그 파일 읽기라 이미 이식성 있음).
  **결정 필요:** `write_bridge_envs:497`의 `TUI_PANE=codex-live:0.0`은 tmux 좌표다 —
  Windows에서 orca 터미널 식별자 의미로 바뀌므로 **기존 키를 재해석할지 새 키를 둘지
  B2-3에서 확정**한다(기존 macOS `.env` 호환 유지가 제약).

---

## Phase 3 — ③ 코덱스 TUI verify 판정

**Files:** `plugins/harness-installer/skills/configure-harness/generator/harnessctl.py`

①에 완전 종속. 재사용 가능한 것과 새로 만들 것이 이미 갈려 있다:

- `_rollout_exists:782` — `json.loads` 비교라 **이미 이식성 있음, 수정 불필요**
- `_is_codex_cmd:772` — **그대로 사용 가능**. Windows codex는 Rust 바이너리라 argv0이
  `codex*`로 잡힌다(롤아웃 `originator: codex_cli_rs` 확인)
- `session_procs:722` → `_session_root_win:709`는 cmdline `-n <세션>` 매칭인데
  이건 **claude 봇 전용 패턴**이다. orca 터미널 안의 codex에는 `-n`이 없다 →
  **`_tui_root_win`(ptyId → 자손 트리)을 새로 만든다.**

- [ ] **T3-1** `judge_codex_tui:799`에 Windows 분기 추가. 루트 탐색만 신설하고
  판정 3단(세션 존재 / codex 생존 / 롤아웃)은 기존 로직 재사용.
  `fix` 안내 문자열도 `bash …/tui-up.sh` → `bridge_win.py tui-up`으로.
- [ ] **T3-2** `harnessctl.py:1064-1066`의 `judge_codex_tui` 리포트를 macOS `else` 밖으로
  꺼내 Windows에서도 사용자에게 노출(현재는 `:1031` 대기 루프 안에서만 호출되어 노출 0).

---

## ② usage-coach — 계약만 고정 (구현은 다른 세션)

usage-coach 내부 포팅은 **다른 세션 소유**다. 이 플랜은 접합부만 고정한다.
`codexbar`가 Windows 공식 빌드가 없다는 것(macOS 앱 + macOS/Linux CLI 타르볼만,
Windows는 커뮤니티 포크 `Finesssee/Win-CodexBar`로 안내)이 그쪽의 근본 제약이다.

**지금 이 플랜이 하는 것 (Phase 0에 포함):**
- [ ] **U-1 웹훅 verify를 Windows에서 켠다** — `harnessctl.py:1085`의 `IS_WIN` 조건 제거.
  `:1087-1102`의 판정 로직은 **한 줄도 안 고친다**(플랫폼 의존 없음).
- [ ] **U-2 install 위임 계약 고정** — `:1124-1125`를
  `usage-coach/scripts/dash_win.py install` 위임으로 교체하되, 파일 부재 시
  `SKIP + "dash_win.py 미도착 — usage-coach Windows 포팅 대기"` 출력.
  schtasks task 이름은 **`UsageCoachDashboard`**로 고정
  (`WIN_AUTOSTART_TASK = "DiscordHarnessBotWin"` 명명 관례 승계 —
  `bot_win.py`의 `TASK_NAME`처럼 양쪽이 **반드시 일치**해야 한다).
- [ ] **U-3 SKIP 문구 정정** — 남는 SKIP의 "2차 범위, 이 수직 슬라이스 밖"은
  "곧 할 것"으로 읽힌다. 실제 사유(codexbar 데이터원 / dash_win.py 대기)로 교체.

**다른 세션에 전달할 계약 3줄:**
1. 진입점 = `usage-coach/scripts/dash_win.py`, 서브커맨드 `install` / `remove`
2. schtasks task 이름 = `UsageCoachDashboard` (5분 간격 = `/sc minute /mo 5`, 관리자 권한 필요)
3. `~/.config/usage-coach/discord.json`은 **플랫폼 무관 유지** — 설치기 verify가 이 경로를 그대로 읽는다

---

## Verification

**Phase마다:**
- `python -m pytest tests/ -q` — 현재 기준선 37 passed / 6 skipped
- `harnessctl.py doctor` — 핀 일치·플러그인 버전·소유자 경로

**Phase 1 완료 시:** 임의 폴더에 `/configure-bot` → 디스코드 실채널 응답 →
`stop`/`start`/`remove` → 폴더 diff 0

**Phase 2 완료 시:** 코덱스 호명 응답 + `logs/daemon.log`의 `로그인:` +
TUI 켠 상태에서 orca 터미널에 codex 생존

**Phase 3 완료 시:** `verify`가 TUI OK 판정, codex 강제 종료 후 FAIL 판정

**전체 완료 시:** Windows E2E 재완주
(preflight→fetch→plugins→pair→install→verify 전 항목 OK, SKIP은 사유가 명시된 것만) →
pins.json 재갱신 + hdmun 포크에 태그 발행

**macOS 게이트(결정 4):** 위 어느 것도 mac을 요구하지 않는다.
mac 수급 후 **내 macOS 기기에 새 pins를 설치하기 직전**에만
`doctor` + `verify` 1회로 회귀 확인한다. 중점 관찰 대상은 `pid_alive:689`
(유일한 실질 macOS 동작 변경, verify의 브리지 데몬 생존 판정 한 줄).

---

## 이 문서의 이력

이 파일의 초안(2026-08-29 오전)은 소유권을 netwaif 전제로 썼고, 순서가 ①브리지 먼저였고,
②를 "영구 SKIP" 권고했고, ④folder-bot이 빠져 있었다. 같은 날 그릴링에서 넷 다 뒤집혀
**전면 교체**했다(파일 경로는 유지). 뒤집힌 근거는 위 Context와 확정 결정에 있다.

이 파일이 모든 후속 세션의 **정본**이다. `~/.claude/plans/` 사본은 세션 임시본이니
참조하지 말 것.

---

# 부록 A — Phase별 모델 배정

프로젝트 CLAUDE.md의 "저비용" 원칙 적용: 판단은 비싼 모델, 구현은 Sonnet,
기계적 반복은 Haiku. effort는 낮게 시작한다.

| Phase | 작업 성격 | 모델 | effort | 근거 |
|---|---|---|---|---|
| **P0-1, P0-7** | 문서 정정 | **Haiku** | low | 내용이 이미 확정됐다. 문장 교체뿐 |
| **P0-2 ~ P0-6** | pins 스키마 + 소비부 파급, origin/마켓플레이스 정정, remove 버그 | **Sonnet** | medium | 일반 구현. 단 P0-2는 `pins()["repos"][name]` 소비부가 str→dict로 바뀌어 파급이 있으니 테스트 우선 |
| **P0-8** | 포크 생성·push | **Haiku** | low | 기계적. 단 외부 상태 변경이라 사용자 승인 게이트 |
| **U-1 ~ U-3** | ② 계약 배선 | **Sonnet** | low | 조건 제거 + 문자열 교체 수준 |
| **Phase 1 (④)** | botctl_win.py 637행 포팅 | **Sonnet** | medium | `bot_win.py` 전례가 있어 설계 미지가 적다. 대량 구현이라 Sonnet이 최적 |
| **B2-1** | 데몬 단독 기동 스파이크 | **Sonnet** | low | 실측 확인. 판단 아님 |
| **B2-3** | `pane.mjs` 인터페이스 설계 | **Opus** | high | 이 플랜에서 유일하게 진짜 설계 판단 — 인터페이스를 유지하면서 macOS 무변경을 보장해야 하고, 틀리면 mac 없이 검증할 방법이 없다. **설계만 Opus, 구현은 Sonnet에 넘긴다** |
| **B2-2, B2-4 ~ B2-6** | spawn 수정, bridge_win.py, 배선 | **Sonnet** | medium | 구현. B2-4는 분량이 크지만 `bot_win.py`+Phase 1 전례 승계 |
| **Phase 3 (③)** | `_tui_root_win` + 리포트 노출 | **Sonnet** | medium | 작다. 재사용 경계가 이미 플랜에 명시돼 있음 |

**요약:** 전 구간 Sonnet 주력. Haiku는 문서·기계적 작업 3건, Opus는 B2-3 설계 1건뿐이다.
Opus를 B2-3 이외에 쓰지 말 것 — 나머지는 전례가 있어 판단 비용이 낮다.

---

# 부록 B — 세션별 이어받기 프롬프트

각 프롬프트는 **기억 0인 새 세션**을 전제로 한다. 그대로 복사해 붙여넣으면 된다.
모든 세션은 `docs/superpowers/plans/2026-08-29-windows-2nd-slice.md`(이 파일)를 정본으로 읽는다.

## 세션 0 — Phase 0 배관 (Sonnet / medium)

```
작업 폴더: C:\Users\hdmun\repo\ref\discord-harness-installer

먼저 docs/superpowers/plans/2026-08-29-windows-2nd-slice.md 를 읽어라. 그게 정본이다.

Phase 0 (P0-1 ~ P0-8)만 수행한다. Phase 1 이후는 손대지 마라.

순서 강제: P0-1(ADR-0002 정정)을 가장 먼저 한다. ①④가 둘 다 schtasks 등록을
늘리므로 "관리자 권한 불필요"라는 틀린 전제를 세 곳에 복제하기 전에 고쳐야 한다.

P0-4는 구현 전에 실측이 필요하다: `claude plugin marketplace add` 가 같은 이름
다른 repo 를 덮어쓰는지 거부하는지 확인하고, 결과에 따라 remove 단계를 넣거나 뺀다.

P0-8(포크 생성·push)은 외부 상태 변경이다. 실행 전에 사용자 승인을 받아라.

완료 조건:
- python -m pytest tests/ -q 가 그린 (현재 기준선 37 passed / 6 skipped)
- harnessctl.py preflight / fetch / doctor 3종이 이 머신에서 hdmun 소유자 경로로 동작
- git status 클린 (커밋 완료)
```

## 세션 1 — Phase 1 folder-bot 포팅 (Sonnet / medium)

```
작업 폴더 2개를 오간다:
- 포크 레포: hdmun/folder-bot 클론 (없으면 gh repo clone 후 위치를 사용자에게 확인)
- 설치기 레포: C:\Users\hdmun\repo\ref\discord-harness-installer

설치기 레포의 docs/superpowers/plans/2026-08-29-windows-2nd-slice.md 를 먼저 읽어라.
Phase 1 (F1-1 ~ F1-4) 만 수행한다.

선행 조건 확인: Phase 0 이 끝나 있어야 한다. pins.json 에 owner 필드가 있고
plugins.folder-bot 이 hdmun 을 가리키는지 확인하고, 아니면 멈추고 보고해라.

핵심 제약 3가지:
1. claude 엔진만 포팅한다. codex 엔진(write_codex_plists:214)은 Phase 2 소관이다 —
   Windows 에서 --engine codex 는 명시적으로 거부하고 사유를 출력한다.
2. botctl.py 원본을 수정하지 마라. botctl_win.py 를 신설한다 (결정 8).
   macOS 회귀를 검증할 mac 이 지금 없다.
3. botctl.py 의 bots.json 은 config_dir()/bots.json (전역) 이고
   하네스의 <work>/bots.json 과 다른 파일·다른 스키마다. bot_win.py 를 그대로
   복사하지 말고 orca·schtasks·프로세스 판정 헬퍼만 재사용해라
   (재사용 목록은 플랜의 Phase 1 절에 file:line 으로 적혀 있다).

완료 조건:
- 임의 폴더에 /configure-bot 으로 봇 추가 → 디스코드 실채널 응답 1회
- stop → start → remove 후 폴더 diff 0
- 계약 테스트 (--dry-run 명령 문자열 + 재실행 멱등) 통과
```

## 세션 2a — B2-1 스파이크만 (Sonnet / low)

```
작업 폴더: hdmun/codex-discord 클론 (없으면 gh repo clone, 위치는 사용자에게 확인)

설치기 레포 C:\Users\hdmun\repo\ref\discord-harness-installer 의
docs/superpowers/plans/2026-08-29-windows-2nd-slice.md 를 먼저 읽어라.

B2-1 스파이크 하나만 한다. 코드를 고치지 마라. 확인만 하고 결과를 보고한다.

내용: .env 에서 TUI_PANE / TUI_CHANNEL_ID 를 빼면 src/tmux.mjs 경로를 타지 않는다.
node --env-file=.env src/index.mjs 를 Windows 에서 손으로 띄워
logs/daemon.log 에 "로그인:" 이 찍히는지 확인하고, 디스코드 수다 채널에서
코덱스를 1회 호명해 응답을 본다.

성공하면: 그대로 보고하고 멈춘다 (B2-2 이후는 다른 세션).
실패하면: 실패 지점을 정확히 보고한다. spawn 계층 문제(codex.cmd)일 가능성이 크다 —
그 경우 B2-2 이후 설계가 통째로 달라지므로 임의로 고치지 말고 보고만 해라.
```

## 세션 2b — B2-3 pane.mjs 설계만 (Opus / high)

```
작업 폴더: hdmun/codex-discord 클론

설치기 레포의 docs/superpowers/plans/2026-08-29-windows-2nd-slice.md 를 먼저 읽어라.

B2-3 의 설계만 한다. 구현은 다음 세션이 한다 — 설계 문서를 남기고 끝내라.

과제: src/tmux.mjs 를 src/pane.mjs 로 바꾸되 공개 인터페이스
(pasteToPane / capturePane / paneCurrentCommand / paneHasCodex / extractSessionId / UUID_RE)
를 그대로 유지하고, 내부만 process.platform 으로 tmux / orca terminal 분기시킨다.

이게 이 프로젝트에서 유일하게 진짜 설계 판단인 이유: macOS 무변경이 성공 기준인데
(src/index.mjs:10 의 호출부를 수정 없이 통과), 지금 mac 이 없어서 회귀를 실측으로
검증할 방법이 없다. 설계로 보장해야 한다.

같이 결정할 것: write_bridge_envs:497 의 TUI_PANE=codex-live:0.0 은 tmux 좌표다.
Windows 에서 orca 터미널 식별자 의미로 바뀌는데, 기존 키를 재해석할지 새 키를 둘지
정해라. 제약은 기존 macOS .env 호환 유지다.

산출물: docs/ 아래 설계 문서 1개 (인터페이스 시그니처, 플랫폼별 구현 매핑 표,
macOS 무변경 근거, TUI_PANE 키 결정과 사유). 코드는 건드리지 마라.
```

## 세션 2c — B2-2, B2-4 ~ B2-6 구현 (Sonnet / medium)

```
작업 폴더 2개를 오간다:
- hdmun/codex-discord 클론
- C:\Users\hdmun\repo\ref\discord-harness-installer

설치기 레포의 docs/superpowers/plans/2026-08-29-windows-2nd-slice.md 와,
세션 2b 가 남긴 pane.mjs 설계 문서를 먼저 읽어라.

선행 조건: B2-1 스파이크가 통과했고 B2-3 설계 문서가 있어야 한다. 없으면 멈춰라.

B2-2 (.cmd spawn 수정), B2-3 구현, B2-4 (bridge_win.py), B2-5 (folder-bot codex 엔진),
B2-6 (설치기 배선) 을 순서대로 한다.

함정 2개를 미리 박아둔다:
1. Windows npm 셔임은 codex.cmd 라 spawn 에 shell:true 또는 cmd /c 경유가 필요하다.
   이 프로젝트에서 WinError 2/193 으로 이미 3회 겪었다.
2. 롤아웃 cwd 비교에 문자열 grep 을 쓰지 마라. Windows 롤아웃은
   "cwd":"C:\\Users\\hdmun" 로 백슬래시가 JSON 이스케이프된다.
   harnessctl.py:_rollout_exists:782 가 json.loads 후 payload.cwd 를 비교하는 방식이니
   그걸 승계해라. tui-up.sh 의 grep -qF 는 Windows 에서 깨진다.

완료 조건:
- 코덱스 호명 응답 + logs/daemon.log 의 "로그인:"
- TUI 켠 상태에서 orca 터미널에 codex 생존
- 설치기 pytest 그린
```

## 세션 3 — Phase 3 TUI verify 판정 (Sonnet / medium)

```
작업 폴더: C:\Users\hdmun\repo\ref\discord-harness-installer

docs/superpowers/plans/2026-08-29-windows-2nd-slice.md 를 먼저 읽어라.
Phase 3 (T3-1, T3-2) 만 수행한다.

선행 조건: Phase 2 가 끝나 브리지 TUI 모드가 Windows 에서 동작해야 한다. 아니면 멈춰라.

재사용 경계가 이미 확정돼 있다. 새로 만들 것은 하나뿐이다:
- _rollout_exists:782 는 이미 이식성 있음 — 수정하지 마라
- _is_codex_cmd:772 는 그대로 사용 가능 — Windows codex 는 Rust 바이너리라
  argv0 이 codex* 로 잡힌다
- session_procs:722 의 _session_root_win:709 는 cmdline "-n <세션>" 매칭인데
  이건 claude 봇 전용 패턴이다. orca 터미널 안의 codex 에는 -n 이 없다 →
  _tui_root_win (ptyId → 자손 트리) 을 새로 만든다

완료 조건:
- verify 가 TUI 켬 상태에서 OK
- codex 를 강제 종료하면 FAIL
- pytest 그린
```

## 세션 4 — 마무리 릴리즈 (Sonnet / low, 사용자 게이트)

```
작업 폴더: C:\Users\hdmun\repo\ref\discord-harness-installer

docs/superpowers/plans/2026-08-29-windows-2nd-slice.md 의 Verification 절을 읽어라.

Windows E2E 를 재완주한다:
preflight → fetch → plugins → pair → install → verify
전 항목 OK 여야 하고, SKIP 은 사유가 명시된 것만 남아야 한다.

통과하면 pins.json 을 갱신하고 hdmun 포크들에 태그를 발행한다.
태그 발행은 외부 상태 변경이므로 사용자 승인을 받아라.

마지막에 SESSION.md 를 갱신한다 (섹션 규칙: 목표=고정, 현재상태·다음단계=덮어쓰기,
결정기록·파일흔적=추가만).

macOS 회귀 확인은 여기 포함하지 마라. mac 수급 후 "내 macOS 기기에 새 pins 를
설치하기 직전" 에만 doctor + verify 1회로 한다 (플랜의 결정 4).
중점 관찰 대상은 pid_alive:689 — 유일한 실질 macOS 동작 변경이고,
verify 의 브리지 데몬 생존 판정 한 줄이다.
```
