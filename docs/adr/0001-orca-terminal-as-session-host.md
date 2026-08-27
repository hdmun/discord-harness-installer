# Windows 세션 호스트를 orca terminal로 한다

Windows에는 tmux가 없고 WSL2는 배제 대상이라 봇 세션을 담을 것이 필요했다. 단순 detached
프로세스(`Start-Process -WindowStyle Hidden`)를 쓰지 않고 orca terminal을 택한 이유는
**돌아가는 claude에 `/exit`를 주입할 채널**이 필요하기 때문이다 — 강제 종료는 유령 리스를
남기고 같은 이름 새 세션의 채널 연결을 로그 없이 스킵시킨다(2026-08-06 실측). orca는
`terminal create/send --text/read --cursor/wait --for tui-idle/list/stop`으로 tmux 원시명령에
1:1 대응한다.

## Consequences

- `orca terminal`은 등록된 worktree 안에서만 생성된다(비-git 폴더에서 `selector_not_found`
  실측). 설치 루트가 git 레포여야 한다는 새 전제가 생긴다.
- 터미널 핸들 `term_<uuid>`는 런타임 발급이라 tmux 세션 이름 같은 안정 식별자가 없다.
  식별은 `title` + `worktreePath`로 하고 매번 `terminal list`로 재해석한다.
- `terminal list/show` 메타데이터에 startup command 필드가 없다. macOS에서 plist가 겸하던
  기동 정본 역할을 orca가 받지 못한다(ADR-0003으로 이어진다).
- 봇 생존이 Orca 런타임 생명주기에 종속된다. 런타임이 죽으면 봇도 죽는다. 헤드리스
  `orca serve`에서의 거동은 착수 전 스파이크로 확인한다 — 실패하면 이 결정을 재검토한다.

## 2026-08-27 스파이크 반영

`/exit` 주입은 실증됐다(`terminal send --text "/exit" --enter`로 claude 정상 종료 확인) —
이 ADR의 핵심 근거가 검증됐다. 확인 과정에서 드러난 것:

- `orca repo`에 **제거 명령이 없다**(`list|add|show|set-base-ref|search-refs`가 전부).
  등록 해제가 CLI로 불가능하므로 `remove`가 등록분을 회수할 수 없다 — 안내로 대체하거나
  등록 자체를 사용자 몫으로 돌려야 한다.
- `wait --for exit`는 **셸** 종료를 기다린다. claude만 죽고 pwsh가 남으면 timeout이므로
  봇 종료 판정에 쓸 수 없다.
- 첫 기동 시 워크스페이스 신뢰 프롬프트가 뜬다. `wait --for tui-idle`이
  `blockedReason: "codex-trust-workspace"`로 알려주므로 검출은 되지만, 무인 봇 전제로는
  설치 절차에서 통과시켜야 한다.
- **앱 종료 시 터미널은 생존한다 — 이 ADR의 최대 리스크가 해소됐다.** 터미널을 소유하는
  것은 Electron 앱이 아니라 별도 `orca-terminal-daemon.exe`이고, 그 데몬은 앱 프로세스 트리
  밖에 있다. 실측에서 데몬과 그 안의 claude 세션이 현재 앱 인스턴스보다 이틀 먼저 떠 있었다
  (앱 재시작을 한 번 이상 살아남음).
- 다만 **생성·제어와 생존은 다른 계층이다.** `create`·`list`·`send`·`read`는 런타임(앱 또는
  `orca serve`)을 요구하고, 생존만 데몬이 보장한다. 앱이 내려간 동안 봇은 계속 돌지만
  재기동은 못 한다.
- 헤드리스 `orca serve`에서 제어 계층이 **전부 동작한다**(`list`·`show`·`read`·`create`·
  `send` 실측 통과). 데스크톱 창이 한 번도 열리지 않아도 완전 무인 운영이 성립한다.
  `serve`는 별도 서버가 아니라 같은 앱을 창 없이 띄우는 모드이고, `orca open`으로 나중에
  창을 붙일 수 있다.
- **터미널 식별을 `title`에 의존하면 안 된다.** 렌더러 측 메타(`title`·`preview`·
  `lastOutputAt`)는 창이 있는 런타임에서만 채워진다 — 헤드리스 `serve`에서는 `null`이고,
  창을 띄우면 되돌아온다(실측). 영구 소실은 아니지만 부트스트랩·재기동이 도는 헤드리스
  시점에 없다는 점이 문제다. 살아남는 것은
  `handle`·`ptyId`·`worktreeId`·`worktreePath`·`connected`뿐이고, 봇 2개가 worktree 하나를
  공유하므로 `worktreePath`만으로는 가를 수 없다. `bots.json`에 `ptyId`를 기록하고
  프로세스 테이블의 `-n <세션명>`으로 교차 확인한다.
