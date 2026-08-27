# Orca 레포 등록은 설치기가 하고 remove는 되돌리지 않는다

`orca terminal`은 등록된 worktree 안에서만 생성되므로(비-git·미등록 폴더에서
`selector_not_found` 실측) Windows 설치에는 `orca repo add`가 필요하다. 그런데 `orca repo`에는
제거 명령이 없다 — `list | add | show | set-base-ref | search-refs`가 전부다. 등록은 CLI로
되는데 해제가 안 된다.

그래도 설치기가 등록을 수행하기로 한다. `cmd_plugins`가 마켓플레이스를 추가하고 플러그인을
설치하지만 `remove`는 그것을 되돌리지 않고 "starter·folder-bot 플러그인과 그 산출물은 remove
범위 밖 — 안내만 한다"로 처리하는 선례와 성격이 같기 때문이다. Orca 레지스트리도 작업 폴더
바깥의 앱 내부 상태다.

## Considered Options

- **등록도 사용자 몫으로**(preflight가 등록 여부만 확인) — "설치기 소유분 diff 0"을 문자
  그대로 지키지만, 수동 단계가 하나 늘고 위 선례와 어긋난다.
- **remove가 Orca 내부 상태 파일을 직접 편집** — 비공개 포맷 의존. 기각.

## Consequences

`remove` 출력에 "Orca 레포 등록은 남는다(제거는 Orca에서 직접)"를 명시한다. E2E 게이트의
diff 0 판정은 **작업 폴더 안 설치기 소유분** 기준임을 재확인한다 — 이 등록은 그 범위 밖이다.
