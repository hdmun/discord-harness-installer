# 부팅 경로 정본 이중화를 감수하고 계약 테스트로 봉인한다

2026-08-04에 정본 이중화를 두 번 기각했다(번들·혼합 수급 / B안 자체 구현 엔진). 이번 건은
그 결정을 부팅 경로에 한해 뒤집는다: macOS bash 229줄(`bot-up.sh`·`bot-restart.sh`·
`install-autostart.sh`)을 무수정 보존하고 Windows용 `bot_win.py`를 병행한다. 근거는 macOS
프로덕션이 E2E 6테이크로 검증됐고 영상·매뉴얼 v2.2가 그 위에 서 있다는 것 — 크로스플랫폼
python 단일 정본으로 갈아엎으면 그 검증이 무효가 된다.

## Consequences

이중화의 대가는 표류다. `bot-up.sh`에는 현장에서 얻은 동작 4개가 들어 있는데
(①전역 락 직렬화 — 동시 기동 시 discord MCP의 `bun install`이 겹쳐 EEXIST 경합
②연결 감시자 fd 분리 — 감시자가 stdout을 붙들면 호출이 240초 블록 ③스테일 락 스틸
④`--permission-mode auto` 세션 플래그 주입), `test/scripts.test.sh`의 단언 3개가 **전부
④에만** 걸려 있다. ①②③은 테스트가 0이라 병행본이 물려받을 안전장치가 없다.

그래서 `bot-up` 계약 4개를 플랫폼 중립 pytest로 신설하고 bash판(subprocess 호출)과
python판에 **같은 단언**을 돌린다. macOS에서는 둘 다, Windows에서는 python판만. 이 테스트
없이 병행본을 머지하지 않는다.
