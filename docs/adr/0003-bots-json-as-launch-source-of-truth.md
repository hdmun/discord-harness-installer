# 기동 정본을 bots.json으로 분리한다

macOS에서는 LaunchAgent plist가 자동 기동 수단과 기동 정본을 겸했다 — `bot-restart.sh`가
`$HOME/Library/LaunchAgents/*.plist`를 훑어 `tmux new-session` 마지막 인자에서 기동 명령을
추출한다. orca terminal은 startup command를 저장하지 않고 schtasks는 부트스트랩만 가리키므로
Windows에서는 이 겸직이 성립하지 않는다. 그래서 기동 정본을 작업 폴더의 `bots.json`으로
분리한다. `folder-bot`이 이미 같은 패턴을 반쯤 갖고 있다(`~/.config/folder-bot/bots.json` +
`build_cmd(bot)`가 명령을 재구성, plist는 파생물).

## Consequences

- 자동 기동을 꺼도 `restart`가 동작한다. macOS 현행 설계의 결함(autostart off면 plist가
  없어 재기동 경로도 같이 죽음)이 Windows 쪽에서는 해소된다.
- 세션 이름이 파일 필드가 되어 옵션화된다. 리스는 세션 이름 + Claude 계정 단위이므로
  (2026-08-10 실측) 같은 계정으로 여러 기기를 운영하려면 이름이 달라야 한다. Windows 기본값은
  `orchestrator-<hostname>`, macOS 기본값은 프로덕션 무회귀를 위해 현행 유지.
- `bots.json`은 양 플랫폼에서 생성하되 당분간 Windows만 읽는다. SESSION.md의 [약속] 항목
  "대시보드에 봇·폴더·채널 매핑 표시"가 필요로 하는 데이터원이 되고, macOS를 plist에서
  떼어낼 때의 이관 경로가 된다.
