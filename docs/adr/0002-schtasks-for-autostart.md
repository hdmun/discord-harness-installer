# Windows 자동 기동을 schtasks onlogon으로 한다

launchd 자리를 채울 후보로 orca automations를 먼저 검토했으나, automations는 agent-backed다
(`--prompt`·`--provider`가 필수) — "`python discord_dash.py`를 5분마다" 같은 범용 프로세스
데몬을 맡을 수 없고, 봇 기동에 필요한 `claude --channels …` 플래그도 전달하지 못한다.
Windows 서비스(`sc.exe`/nssm)는 세션 0 격리 때문에 GUI 앱인 Orca를 띄우지 못해 ADR-0001과
상극이다. 남은 것이 `schtasks /sc onlogon`이고, 관리자 권한이 필요 없으며 지연·재시도를
표현할 수 있어 시작프로그램 폴더보다 낫다.

## Consequences

등록 작업이 실행하는 것은 봇이 아니라 **부트스트랩 스크립트**다. 스크립트가 orca 런타임을
기동·대기한 뒤 `bots.json`을 순회해 `terminal list`에 없는 봇만 생성한다(멱등).

## 2026-08-27 스파이크 반영

부트스트랩이 띄우는 것은 **`orca serve`**(창 없는 기동)다. `orca serve`는 별도 경량 서버가
아니라 Orca 앱(Electron)을 창 없이 띄우는 모드이며 — `serve`가 만든 프로세스가 그대로
`Orca.exe`다 — 그 런타임에 사용자가 나중에 `orca open`으로 창을 붙일 수 있다(충돌 없음,
`runtimeId` 유지, 재시작 없음). 따라서 로그온 시 조용히 기동하고 필요할 때 창을 여는 조합이
성립한다.

이미 런타임이 떠 있으면 `serve`는 `[single-instance]` 메시지와 함께 exit 3을 낸다 —
부트스트랩은 이 코드를 **"이미 기동됨"으로 취급**하고 진행한다(실패로 보면 안 된다).

부수 효과: 봇 생존 자체는 `orca-terminal-daemon.exe`가 보장하므로 런타임이 내려가도 봇은
계속 돈다. 다만 그동안 `terminal list`가 `runtime_unavailable`을 내며 **관리가 불가능**하다
(생성·주입·읽기 전부). 부트스트랩과 `restart`는 런타임 가용을 선행 조건으로 갖는다.
