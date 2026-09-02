#!/usr/bin/env python3
"""discord-harness 통합 설치기 결정적 엔진 — 매뉴얼 16장을 대체한다.

경로는 전부 HOME 환경변수 기준(테스트가 HOME을 tmpdir로 돌린다).
A안 위임 오케스트레이터: 정본이 없는 접합부만 직접, 설치 동작은 정본 스크립트에 위임.
오버레이는 manifest를 읽어 복사만 한다(창작 금지).
launchctl로 job을 내리지 않는다(부팅 job은 프로세스 그룹째 킬 위험, 2026-07-31 실측)
— plist 파일 생성/삭제 + tmux kill-session만. (Task 13이 소스 전체에 해당 launchctl
서브커맨드 문자열이 없음을 정적 검증하므로 이 파일에 그 단어를 쓰지 말 것.)
비밀(토큰·웹훅)은 파일로만 수령하고 stdout에 출력하지 않는다.
"""
import argparse, base64, ctypes, hashlib, json, os, plistlib, re, shutil, stat, subprocess, sys, time
from datetime import datetime
from pathlib import Path

IS_WIN = sys.platform == "win32"

if IS_WIN:
    # 콘솔 기본 코드페이지(cp949)는 로그의 em-dash·한글에 UnicodeEncodeError로
    # 죽는다(discord-multiagent/scripts/bot_win.py와 동일 실측) — UTF-8 강제.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCHEMA_VERSION = 1
ROLES = ("orch", "claude", "codex", "gemini")
REPO_NAMES = ("discord-multiagent", "codex-discord", "usage-coach")
PLUGIN_NAMES = ("multi-agent-starter", "folder-bot")
BLOCK_START = "<!-- discord-multiagent:start -->"
BLOCK_END = "<!-- discord-multiagent:end -->"
ORCH_PLIST_LABEL = "com.discord-multiagent.orchestrator"
CHAT_PLIST_LABEL = "com.discord-harness.chat-claude"
CHAT_SESSION = "chat-claude"

def home() -> Path: return Path(os.environ.get("HOME") or os.environ["USERPROFILE"])
def config_dir() -> Path: return home() / ".config/discord-harness"
def state_path() -> Path: return config_dir() / "state.json"
def repos_dir() -> Path: return home() / ".local/share/discord-harness/repos"
def harness_repo() -> Path: return repos_dir() / "discord-multiagent"
def bridge_repo() -> Path: return repos_dir() / "codex-discord"
def coach_repo() -> Path: return repos_dir() / "usage-coach"
def now() -> str: return datetime.now().isoformat(timespec="seconds")

def version_tuple(v: str) -> tuple:
    nums = re.findall(r"\d+", v)
    return tuple(int(x) for x in nums[:3]) or (0,)

def installed_plugin_version(name: str):
    base = home() / ".claude/plugins/cache" / name / name
    if not base.is_dir():
        return None
    vers = [d.name for d in base.iterdir() if d.is_dir()]
    return max(vers, key=version_tuple) if vers else None

def pins() -> dict:
    return json.loads((Path(__file__).resolve().parent / "pins.json").read_text(encoding="utf-8"))

def pin_owner(entry: dict) -> str:
    """schema_version 2 — owner 미지정 시 netwaif 폴백(결정 2)."""
    return entry.get("owner", "netwaif")

def repo_url(name: str) -> str:
    # HARNESS_REPO_BASE는 테스트 시임 우선순위 그대로 보존 — owner 해석은 그 아래.
    base = os.environ.get("HARNESS_REPO_BASE")
    if base:
        return f"{base}/{name}"
    owner = pin_owner(pins()["repos"][name])
    return f"https://github.com/{owner}/{name}.git"

def load_state() -> dict:
    if not state_path().exists():
        return {"schema_version": SCHEMA_VERSION, "work_dir": None,
                "repos": {}, "steps": {}, "overlay": {}, "mcp_added": [], "lines_added": {}}
    return json.loads(state_path().read_text(encoding="utf-8"))

def save_state(st: dict) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    state_path().write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def run_git(args, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)

def rmtree_force(p: Path) -> None:
    """git .git/objects/* 는 읽기전용 파일 — Windows shutil.rmtree는 그대로 두면
    PermissionError([WinError 5])로 죽는다(실측). 읽기전용 해제 후 재시도."""
    def _on_error(func, path, exc_info):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    shutil.rmtree(p, onerror=_on_error)

def bash_bin() -> str:
    """PATH의 bare "bash"는 Windows에서 CreateProcess 검색 순서상 System32의 WSL
    런처 스텁을 먼저 잡을 수 있다(실측: shutil.which는 Git Bash를 찾는데 실제
    실행은 WSL bash로 튀어 "No such file or directory") — 항상 전체 경로로 지정."""
    return shutil.which("bash") or "bash"

def secure_file(p: Path) -> None:
    """비밀 파일(토큰·웹훅) 보호 — POSIX는 chmod 0600, Windows는 무시되므로(스파이크
    실측) icacls로 상속 제거 + 현재 사용자 단독 허용(ADR 결정 10)."""
    if IS_WIN:
        user = os.environ.get("USERNAME", "")
        subprocess.run(["icacls", str(p), "/inheritance:r", "/grant:r", f"{user}:F"],
                       capture_output=True, text=True)
    else:
        p.chmod(0o600)

def find_tmux() -> str:
    for c in (shutil.which("tmux"), "/opt/homebrew/bin/tmux", "/usr/local/bin/tmux"):
        if c and Path(c).exists():
            return c
    sys.exit("오류: tmux를 찾을 수 없음 — brew install tmux")

def resolve_work_dir(a) -> Path:
    wd = getattr(a, "work_dir", None) or load_state().get("work_dir")
    if not wd:
        sys.exit("오류: 작업 폴더를 알 수 없음 — --work-dir 지정(또는 pair/install 선행)")
    return Path(wd).expanduser()

def cmd_preflight(a) -> None:
    fails = 0
    def rep(level, msg):
        nonlocal fails
        if level == "FAIL":
            fails += 1
        print(f"[{level}] {msg}")
    rep("OK" if sys.platform in ("darwin", "win32") else "FAIL",
        f"플랫폼: {sys.platform}" + ("" if sys.platform in ("darwin", "win32")
                                    else " — macOS 또는 Windows만 지원"))
    if IS_WIN:
        tools = (
            ("git", "FAIL", "https://git-scm.com/download/win"),
            ("orca", "FAIL", "https://orca.dev — 세션 호스트(tmux 대체, ADR-0001)"),
            ("pwsh", "FAIL", "winget install Microsoft.PowerShell (PowerShell 7+, 프로세스 판정에 필요)"),
            ("node", "FAIL", "https://nodejs.org (브리지는 Node 22+)"),
            ("bun", "FAIL", "https://bun.sh (discord 플러그인 MCP 실행기)"),
            ("claude", "FAIL", "https://claude.com/claude-code 설치"),
            ("codex", "FAIL", "npm i -g @openai/codex (수다 브리지 필수)"),
            ("agy", "WARN", "없으면 제미나이 봇만 빠짐"),
            ("bash", "FAIL", "Git for Windows 동봉 — remove의 uninstall.sh 위임,"
                             " multi-agent-starter .sh 3종에 필요"),
        )
    else:
        tools = (
            ("git", "FAIL", "xcode-select --install"),
            ("tmux", "FAIL", "brew install tmux"),
            ("node", "FAIL", "brew install node (브리지는 Node 22+)"),
            ("bun", "FAIL", "curl -fsSL https://bun.sh/install | bash (discord 플러그인 MCP 실행기)"),
            ("claude", "FAIL", "https://claude.com/claude-code 설치"),
            ("codex", "FAIL", "npm i -g @openai/codex (수다 브리지 필수)"),
            ("agy", "WARN", "없으면 제미나이 봇만 빠짐"),
        )
    for tool, miss_level, hint in tools:
        found = shutil.which(tool)
        if tool == "bash" and found:
            found = bash_bin()  # WSL 스텁 회피 경로(:85-89) 그대로 재사용
        rep("OK" if found else miss_level, f"{tool}: {found or '없음 — ' + hint}")
    plug = home() / ".claude/plugins/cache/claude-plugins-official/discord"
    rep("OK" if plug.is_dir() else "FAIL",
        f"discord 플러그인: {plug if plug.is_dir() else '미설치 — claude 안에서 /plugin 으로 discord 설치'}")
    if IS_WIN:
        work = Path(getattr(a, "work_dir", None) or os.getcwd()).expanduser()
        if not work.is_dir():
            rep("FAIL", f"작업 폴더 없음: {work}")
            sys.exit(1 if fails else 0)
        r = run_git(["rev-parse", "--is-inside-work-tree"], cwd=work)
        if r.returncode == 0 and r.stdout.strip() == "true":
            rep("OK", f"git 레포: {work}")
        else:
            rep("FAIL", f"git 레포 아님: {work} — orca terminal은 등록된 worktree 안에서만 "
                        "생성된다(ADR-0005 결정 8). `git init` 후 재시도(설치기가 대신 실행하지 않음)")
        lp = run_git(["config", "--get", "core.longpaths"], cwd=work)
        if lp.stdout.strip() != "true":
            rep("WARN", "git core.longpaths 미설정 — 정본 레포 clone 중 "
                        "'Filename too long' 가능(실측). `git config --global core.longpaths true` 권고")
        else:
            rep("OK", "git core.longpaths=true")
    # 동명 세션 충돌 검사(플랫폼 무관, 9/2 이월 ①) — 미페어링 상태(bots.json 없음)
    # 한정: 페어링 후엔 이 프로세스가 자기 자신의 봇 세션일 수 있어 오탐이 된다.
    wd_arg = getattr(a, "work_dir", None)
    if wd_arg:
        work = Path(wd_arg).expanduser()
        if work.is_dir() and load_bots_json(work) is None:
            for name in (default_session_name("orch"), default_session_name("chat")):
                if session_procs(name) is not None:
                    rep("FAIL", f"세션 이름 충돌: '{name}' 이미 로컬에서 가동 중 — "
                                "다른 폴더의 하네스 설치이거나 잔존 세션(2026-08-10 실측). "
                                "먼저 그 세션을 /exit로 정리하거나 다른 이름을 쓸 것")
    sys.exit(1 if fails else 0)

def cmd_fetch(a) -> None:
    pin_repos = pins()["repos"]
    repos_dir().mkdir(parents=True, exist_ok=True)
    st = load_state()
    for name in REPO_NAMES:
        dst = repos_dir() / name
        if not dst.exists():
            r = run_git(["clone", "--quiet", repo_url(name), str(dst)])
            if r.returncode != 0:
                sys.exit(f"오류: {name} clone 실패 — {r.stderr.strip()}\n"
                         f"다음 행동: 네트워크 확인 후 fetch 재실행(멱등)")
        else:
            # owner가 pins에서 바뀌었는데 기존 클론이 남아 있으면(이 머신 포함) origin이
            # 낡은 owner를 계속 가리켜 조용히 무효가 된다(결정 3) — fetch 전에 정정.
            expected = repo_url(name)
            cur_origin = run_git(["remote", "get-url", "origin"], cwd=dst).stdout.strip()
            if cur_origin and cur_origin.rstrip("/").removesuffix(".git") != expected.rstrip("/").removesuffix(".git"):
                run_git(["remote", "set-url", "origin", expected], cwd=dst)
                print(f"fetch: {name} origin 정정 {cur_origin} -> {expected}")
            run_git(["fetch", "--tags", "--quiet", "origin"], cwd=dst)
        if a.latest:
            head = run_git(["rev-parse", "--abbrev-ref", "origin/HEAD"], cwd=dst).stdout.strip()
            branch = head.split("/", 1)[1] if "/" in head else "main"
            run_git(["checkout", "--quiet", branch], cwd=dst)
            run_git(["pull", "--ff-only", "--quiet"], cwd=dst)
            ref = "latest"
        else:
            ref = pin_repos[name]["ref"]
            r = run_git(["checkout", "--quiet", ref], cwd=dst)
            if r.returncode != 0:
                sys.exit(f"오류: {name} 핀 {ref} 체크아웃 실패 — {r.stderr.strip()}\n"
                         f"다음 행동: fetch --latest 로 우회하거나 pins.json 확인")
        commit = run_git(["rev-parse", "HEAD"], cwd=dst).stdout.strip()
        st["repos"][name] = {"ref": ref, "commit": commit}
        print(f"fetch: {name} @ {ref} ({commit[:8]})")
    st["steps"]["fetch"] = now()
    save_state(st)

def plugin_cmds(host: str) -> list[list[str]]:
    """marketplace add는 같은 이름을 새 source로 덮어쓴다(거부하지 않음 — 실측
    2026-08-29, 로컬 디렉터리 source로 확인). 그래서 owner가 바뀐 뒤에도 remove
    단계 없이 add 재호출만으로 재등록이 끝난다(결정 7)."""
    cmds = []
    pn = pins()["plugins"]
    for name in PLUGIN_NAMES:
        repo = f"{pin_owner(pn[name])}/{name}"
        cmds.append([host, "plugin", "marketplace", "add", repo])
        cmds.append([host, "plugin", "install", f"{name}@{name}"])
    return cmds

def win_exec_argv(argv: list[str]) -> list[str]:
    """.cmd/.bat 셔임은 CreateProcess가 직접 못 띄운다(WinError 193/2) — cmd.exe /c 경유(bot_win.py 동형)."""
    if IS_WIN:
        exe = shutil.which(argv[0])
        if exe and exe.lower().endswith((".cmd", ".bat")):
            return ["cmd", "/c", subprocess.list2cmdline([exe, *argv[1:]])]
    return argv

def cmd_plugins(a) -> None:
    ok = True
    for argv in plugin_cmds(a.host):
        line = " ".join(argv)
        if a.dry_run:
            print(line)
            continue
        try:
            r = subprocess.run(win_exec_argv(argv), capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=120)
            failed, detail = r.returncode != 0, (r.stderr or r.stdout).strip()[:200]
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            failed, detail = True, str(e)
        if failed:
            ok = False
            print(f"[FAIL] {line} — {detail}")
            print(f"  수동 폴백: 터미널에서 `{line}` 직접 실행, 또는 {a.host} 대화에서 "
                  f"`/plugin marketplace add {argv[-1]}` 후 /plugin 으로 설치")
        else:
            print(f"[OK] {line}")
    if ok and not a.dry_run:
        st = load_state(); st["steps"]["plugins"] = now(); save_state(st)
    sys.exit(0 if ok else 1)

def read_token_file(work: Path, role: str) -> str:
    f = work / f".bot-token-{role}"
    if not f.exists():
        sys.exit(f"오류: 토큰 파일 없음 — {f}\n다음 행동: pbpaste > {f.name} && chmod 600 {f.name}")
    tok = f.read_text(encoding="utf-8").strip()
    if not tok:
        sys.exit(f"오류: 토큰 파일이 비어 있음 — {f}")
    return tok

def write_state_dir(state_dir: Path, token: str, channel_id: str,
                    approver: str, require_mention: bool) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "inbox").mkdir(exist_ok=True)
    env = state_dir / ".env"
    # newline="" 필수 — 기본값이면 Windows에서 \n이 \r\n으로 번역되고, discord
    # 플러그인 파서가 트레일링 \r을 안 잘라내 토큰 값이 깨진다(실측 2026-08-29,
    # MCP 로그: "DISCORD_BOT_TOKEN required" — 파일엔 토큰이 멀쩡히 있는데도 발생).
    env.write_text(f"DISCORD_BOT_TOKEN={token}\n", encoding="utf-8", newline="")
    secure_file(env)
    access = {"dmPolicy": "allowlist", "allowFrom": [approver],
              "groups": {channel_id: {"requireMention": require_mention, "allowFrom": [approver]}},
              "pending": {}}
    (state_dir / "access.json").write_text(json.dumps(access, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

WIN_AUTOSTART_TASK = "DiscordHarnessBotWin"  # discord-multiagent scripts/bot_win.py TASK_NAME과 반드시 일치
WIN_DASHBOARD_TASK = "UsageCoachDashboard"  # usage-coach scripts/install.ps1 $taskName과 반드시 일치

def bots_json_path(work: Path) -> Path:
    return work / "bots.json"

def load_bots_json(work: Path):
    p = bots_json_path(work)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None

def bot_sessions(work: Path) -> dict:
    """{"orch": 세션명, "chat": 세션명} — bots.json이 있으면 그걸(Windows는 호스트
    접미사 포함 가능, 결정 9), 없으면 macOS 레거시 기본값(구버전 설치·미페어링)."""
    data = load_bots_json(work)
    m = {}
    if data:
        for bot in data.get("bots", []):
            if bot.get("name") == "orchestrator":
                m["orch"] = bot.get("session", "orchestrator")
            elif bot.get("name") == CHAT_SESSION:
                m["chat"] = bot.get("session", CHAT_SESSION)
    m.setdefault("orch", "orchestrator")
    m.setdefault("chat", CHAT_SESSION)
    return m

def default_session_name(role: str) -> str:
    """Windows 기본값은 호스트 접미사 포함 — 같은 클로드 계정으로 macOS 프로덕션과
    세션 이름이 겹치면 채널 연결이 로그 없이 스킵된다(2026-08-10 실측, 결정 9).
    macOS 기본값은 현행 유지(프로덕션 무회귀)."""
    base = "orchestrator" if role == "orch" else CHAT_SESSION
    if IS_WIN:
        return f"{base}-{os.environ.get('COMPUTERNAME', 'win')}"
    return base

def bot_claude_args(session: str) -> list:
    return ["-n", session, "--remote-control", session,
            "--channels", "plugin:discord@claude-plugins-official"]

def write_bots_json(work: Path, st: dict) -> list:
    """기동 명령 정본(ADR 결정 4) — Windows bot_win.py가 이 파일을 읽어 up/restart/
    autostart-boot의 claude 인자를 재구성한다. macOS는 아직 읽지 않지만 향후 이관
    경로이자 대시보드 [약속] "봇·폴더·채널 매핑 표시"의 데이터원.

    st["overlay"]에 등록해야 cmd_remove의 회수 루프(:932-940 동형)가 이 파일을
    잡는다 — 미등록이면 "remove 후 diff 0" 계약을 조용히 위반한다(P0-6)."""
    orch, chat = default_session_name("orch"), default_session_name("chat")
    data = {
        "schema_version": 1,
        "bots": [
            {"name": "orchestrator", "folder": str(work),
             "state_dir": str(work / ".discord-state"), "session": orch,
             "remote_control": True, "autostart": True,
             "claude_args": bot_claude_args(orch)},
            {"name": CHAT_SESSION, "folder": str(work / "chat"),
             "state_dir": str(work / "chat/.discord-state"), "session": chat,
             "remote_control": True, "autostart": True,
             "claude_args": bot_claude_args(chat)},
        ],
    }
    p = bots_json_path(work)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="")
    st["overlay"]["bots.json"] = sha256(p)
    return [f"bots.json 생성: {p}"]

def schtasks_registered(name: str) -> bool:
    r = subprocess.run(["schtasks", "/query", "/tn", name], capture_output=True)
    return r.returncode == 0

def cmd_pair(a) -> None:
    work = Path(a.work_dir).expanduser()
    env_path = work / ".env"
    if env_path.exists() and not a.force:
        sys.exit(f"오류: {env_path} 이미 존재 — 덮어쓰려면 --force")
    tokens = {role: read_token_file(work, role) for role in ROLES}
    env_path.write_text(
        f"WORK_CHANNEL_ID={a.work_channel_id}\n"
        f"CHAT_CHANNEL_ID={a.chat_channel_id}\n"
        f"APPROVER_USER_ID={a.approver_user_id}\n"
        f"ORCH_BOT_TOKEN={tokens['orch']}\n"
        f"CLAUDE_BOT_TOKEN={tokens['claude']}\n"
        f"CODEX_BOT_TOKEN={tokens['codex']}\n"
        f"GEMINI_BOT_TOKEN={tokens['gemini']}\n",
        encoding="utf-8", newline="")  # write_state_dir와 동형 CRLF 함정 방지
    secure_file(env_path)
    write_state_dir(work / ".discord-state", tokens["orch"], a.work_channel_id,
                    a.approver_user_id, False)
    write_state_dir(work / "chat/.discord-state", tokens["claude"], a.chat_channel_id,
                    a.approver_user_id, True)
    if a.webhook_url_file:
        wf = Path(a.webhook_url_file).expanduser()
        if not wf.exists():
            sys.exit(f"오류: 웹훅 URL 파일 없음 — {wf}")
        uc = home() / ".config/usage-coach"
        uc.mkdir(parents=True, exist_ok=True)
        cfg_path = uc / "discord.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        cfg["webhook_url"] = wf.read_text(encoding="utf-8").strip()
        # 대시보드 "봇 세션" 카드가 이 설치를 가리키게 한다 — 기본값은 정본 저자의
        # 프로덕션 절대경로라 다른 계정에서는 전부 "브리지 꺼짐"으로 보인다
        cfg["bridges"] = [
            {"name": "Codex", "kind": "codex",
             "dir": str(bridge_repo() / "data"), "env": str(bridge_repo() / ".env")},
            {"name": "Gemini", "kind": "agy",
             "dir": str(bridge_repo() / "data-gemini"), "env": str(bridge_repo() / ".env.gemini")},
        ]
        cfg["claude_bots"] = [
            {"name": "Claude", "kind": "claude", "cwd": str(work)},
            {"name": "Claude", "kind": "claude", "cwd": str(work / "chat")},
        ]
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        secure_file(cfg_path)
        wf.unlink()
    for role in ROLES:
        (work / f".bot-token-{role}").unlink()
    st = load_state()
    for line in write_bots_json(work, st):
        print(line)
    st["work_dir"] = str(work)
    st["steps"]["pair"] = now()
    save_state(st)
    print(f"페어링 완료: {env_path} (0600) + 상태 폴더 2벌, 토큰 파일 4개 삭제")

def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load_manifest() -> dict:
    mp = harness_repo() / "install/overlay-manifest.json"
    if not mp.exists():
        sys.exit(f"오류: 오버레이 manifest 없음 — {mp}\n"
                 f"다음 행동: harnessctl.py fetch 선행(핀이 manifest 포함 버전인지 doctor 로 확인)")
    mf = json.loads(mp.read_text(encoding="utf-8"))
    if mf.get("schema_version") != SCHEMA_VERSION:
        sys.exit(f"오류: manifest schema_version {mf.get('schema_version')} ≠ {SCHEMA_VERSION}"
                 f" — 설치기 업데이트 필요")
    return mf

def apply_overlay(work: Path, st: dict) -> list[str]:
    mf = load_manifest()
    out = []
    for item in mf["overlay"]:
        src, dst = harness_repo() / item["src"], work / item["dst"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        if item.get("merge") == "json-mcp-servers" and dst.exists():
            cur = json.loads(dst.read_text(encoding="utf-8"))
            add = json.loads(src.read_text(encoding="utf-8"))
            added = [k for k in add.get("mcpServers", {})
                     if k not in cur.setdefault("mcpServers", {})]
            for k in added:
                cur["mcpServers"][k] = add["mcpServers"][k]
            if added:
                dst.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                st["mcp_added"] = sorted(set(st.get("mcp_added", []) + added))
                out.append(f"오버레이(병합): {dst} += {added}")
            continue
        if item.get("merge") == "append-lines" and dst.exists():
            cur_lines = dst.read_text(encoding="utf-8").splitlines()
            cur_rstripped = {c.rstrip() for c in cur_lines}
            new_lines = [line for line in src.read_text(encoding="utf-8").splitlines()
                        if line.rstrip() not in cur_rstripped]
            if new_lines:
                cur_lines.extend(new_lines)
                dst.write_text("\n".join(cur_lines) + "\n", encoding="utf-8")
                added_rec = st.setdefault("lines_added", {})
                existing = added_rec.get(item["dst"], [])
                added_rec[item["dst"]] = existing + [l for l in new_lines if l not in existing]
                out.append(f"오버레이(줄 추가): {dst} += {len(new_lines)}줄")
            continue
        if not (dst.exists() and dst.read_bytes() == src.read_bytes()):
            shutil.copyfile(src, dst)
            out.append(f"오버레이: {dst}")
        dst.chmod(int(item.get("mode", "644"), 8))
        st["overlay"][item["dst"]] = sha256(dst)
    body = extract_block((harness_repo() / mf["claude_block"]["src"]).read_text(encoding="utf-8"))
    out += install_claude_block(work / "CLAUDE.md", body)
    return out

def apply_seeds(work: Path, st: dict) -> list[str]:
    out = []
    for item in load_manifest().get("seeds", []):
        src, dst = harness_repo() / item["src"], work / item["dst"]
        if dst.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        st["overlay"][item["dst"]] = sha256(dst)
        out.append(f"시드: {dst}")
    return out

def extract_block(text: str) -> str:
    if BLOCK_START not in text or BLOCK_END not in text:
        sys.exit(f"오류: 정본 CLAUDE.md에 마커 블록 없음 ({BLOCK_START})")
    return text.split(BLOCK_START, 1)[1].split(BLOCK_END, 1)[0]

def install_claude_block(md: Path, body: str) -> list[str]:
    cur = md.read_text(encoding="utf-8") if md.exists() else ""
    if BLOCK_START in cur:
        return []
    md.write_text(cur + f"\n{BLOCK_START}{body}{BLOCK_END}\n", encoding="utf-8")
    return [f"CLAUDE.md 블록 설치: {md}"]

def remove_claude_block(md: Path) -> list[str]:
    if not md.exists():
        return []
    cur = md.read_text(encoding="utf-8")
    if BLOCK_START not in cur or BLOCK_END not in cur:
        return []
    pre, rest = cur.split(BLOCK_START, 1)
    _, post = rest.split(BLOCK_END, 1)
    md.write_text(pre.rstrip("\n") + ("\n" if pre.strip() else "") + post.lstrip("\n"), encoding="utf-8")
    return [f"CLAUDE.md 블록 제거: {md}"]

def parse_env(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out

def write_bridge_envs(work: Path) -> list[str]:
    if not (work / ".env").exists():
        sys.exit(f"오류: {work / '.env'} 없음 — pair 선행 필요(SKILL 7단계)")
    env = parse_env(work / ".env")
    # 작업 폴더는 봇별 분리 — 정본 실측(~/ai-folder/{codex,gemini}-discord-workspace)과
    # 동일 토폴로지. chat/ 은 수다 클로드 전용(공유 시 동시 파일 작업 충돌)
    workdirs = {".env": work / "codex-discord-workspace",
                ".env.gemini": work / "gemini-discord-workspace"}
    for d in workdirs.values():
        d.mkdir(exist_ok=True)
    out = []
    plans = [(".env", env["CODEX_BOT_TOKEN"], "코덱스",
              # 프로덕션 실측과 동일하게 코덱스는 TUI 모드 — tmux 세션(codex-live)에서
              # 작업 과정을 볼 수 있다. 수다 채널 = TUI 채널
              ["TUI_PANE=codex-live:0.0", f"TUI_CHANNEL_ID={env['CHAT_CHANNEL_ID']}"]),
             (".env.gemini", env["GEMINI_BOT_TOKEN"], "제미나이",
              ["ENGINE=agy", "DATA_DIR=data-gemini",
               f"AGY_BIN={shutil.which('agy') or 'agy'}"])]
    for fname, token, trigger, extra in plans:
        p = bridge_repo() / fname
        if p.exists():
            continue  # 멱등 — 기존(사용자 수정 포함) 보존
        lines = [f"DISCORD_TOKEN={token}",
                 f"ALLOWED_USER_IDS={env['APPROVER_USER_ID']}",
                 f"CODEX_WORKDIR={workdirs[fname]}",
                 f"CHANNEL_IDS={env['CHAT_CHANNEL_ID']}",
                 f"NAME_TRIGGER_CHANNEL_IDS={env['CHAT_CHANNEL_ID']}",
                 f"TRIGGER_NAME={trigger}", *extra]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        secure_file(p)
        out.append(f"브리지 환경 조립: {p}")
    return out

BOT_SETTINGS_ALLOW = ["mcp__plugin_discord_discord", "mcp__plugin_discord_discord__reply"]

def write_bot_settings(work: Path, st: dict) -> list[str]:
    """무인 봇 전제 조건: discord reply 도구·MCP 서버를 설치 시점에 사전 승인.

    오케(<work>)·수다(<work>/chat) 양쪽 .claude/settings.local.json 에
    병합 기록하고, 추가분만 state 에 남겨 remove 가 회수한다."""
    out = []
    rec = st.setdefault("settings_added", {})
    for d in (work, work / "chat"):
        p = d / ".claude/settings.local.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        created = not p.exists()
        cur = {} if created else json.loads(p.read_text(encoding="utf-8"))
        entry = {"created": created, "allow": [], "eams": False,
                 "statusline": False, "mode": False}
        if not cur.get("enableAllProjectMcpServers"):
            cur["enableAllProjectMcpServers"] = True
            entry["eams"] = True
        # 무인 권한 모드는 여기(프로젝트 settings)가 아니라 bot-up.sh의 세션
        # 플래그(--permission-mode auto, discord-multiagent v0.1.1)가 담당한다 —
        # 프로젝트 스코프 defaultMode는 효력이 없음이 실측됨(2026-08-05, 0.1.8
        # 시도 철회). entry["mode"]는 0.1.8 설치분 회수용으로 유지.
        allow = cur.setdefault("permissions", {}).setdefault("allow", [])
        for perm in BOT_SETTINGS_ALLOW:
            if perm not in allow:
                allow.append(perm)
                entry["allow"].append(perm)
        if "statusLine" not in cur:
            # 대시보드 '봇 세션' 클로드 카드의 데이터원 — statusLine 훅이 세션
            # 스냅샷을 남긴다(usage-coach 정본). 미주입 시 카드가 영구 공백
            # (2026-08-05 실측). 사용자가 이미 설정한 statusLine은 건드리지 않는다.
            cur["statusLine"] = {
                "type": "command",
                "command": f"bash {coach_repo()}/scripts/statusline-command.sh"}
            entry["statusline"] = True
        rel = p.relative_to(work).as_posix()  # state.json 키는 플랫폼 무관 forward-slash 통일
        if entry["allow"] or entry["eams"] or entry["statusline"] or entry["mode"]:
            p.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if rel not in rec:
                rec[rel] = entry
            out.append(f"봇 권한 사전 승인: {p} (discord reply + MCP 서버 + statusLine"
                       " + 무인 모드)")
    return out

def build_chat_cmd(work: Path) -> str:
    chat = work / "chat"
    path_esc = os.environ.get("PATH", "").replace("&", "&amp;")
    parts = [f"cd {chat}",
             f'export PATH="{path_esc}"',
             f"export DISCORD_STATE_DIR={chat}/.discord-state",
             f"exec {work}/scripts/bot-up.sh -n {CHAT_SESSION} --remote-control {CHAT_SESSION}"
             " --channels plugin:discord@claude-plugins-official"]
    return "/bin/zsh -lc '" + "; ".join(parts) + "'"

def chat_plist_path() -> Path:
    return home() / f"Library/LaunchAgents/{CHAT_PLIST_LABEL}.plist"

def write_chat_plist(work: Path) -> list[str]:
    p = chat_plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"Label": CHAT_PLIST_LABEL,
            "ProgramArguments": [find_tmux(), "new-session", "-d", "-s", CHAT_SESSION,
                                 build_chat_cmd(work)],
            "RunAtLoad": True}
    blob = plistlib.dumps(data)
    if p.exists() and p.read_bytes() == blob:
        return []
    p.write_bytes(blob)
    return [f"plist 생성: {p} (다음 부팅부터 수다 클로드 자동 기동)"]

def delegate(argv: list, cwd: Path, dry: bool, log_hint: str) -> None:
    line = " ".join(str(x) for x in argv)
    if dry:
        print(f"위임(dry-run): (cd {cwd}) {line}")
        return
    # Git Bash(MSYS)는 백슬래시를 이스케이프로 파싱해 인자를 뭉갠다(실측:
    # "C:\Users\..." → "C:Users..."). posix 표기로 넘기면 정상 동작.
    real_argv = [x.as_posix() if isinstance(x, Path) else str(x) for x in argv]
    r = subprocess.run(real_argv, cwd=cwd)
    if r.returncode != 0:
        sys.exit(f"오류: 위임 스크립트 실패(exit {r.returncode}) — {line}\n"
                 f"로그: {log_hint}\n다음 행동: 원인 해결 후 install 재실행(멱등)")

def mcp_log_dir(workdir: Path) -> Path:
    if IS_WIN:
        # S2 확정(docs/spikes/2026-08-27-windows-spikes.md 실측): \/:.를 - 로 맹글링,
        # 경로에 Cache 세그먼트 추가.
        mangled = re.sub(r"[\\/:.]", "-", str(workdir))
        local_appdata = Path(os.environ.get("LOCALAPPDATA", str(home())))
        return (local_appdata / "claude-cli-nodejs" / "Cache" / mangled /
                "mcp-logs-plugin-discord-discord")
    mangled = re.sub(r"[/.]", "-", str(workdir))
    return home() / "Library/Caches/claude-cli-nodejs" / mangled / "mcp-logs-plugin-discord-discord"

def judge_mcp(workdir: Path, since: float = None):
    """MCP 연결 판정 — since(설치 시각) 이전 로그는 무시하고 최신 파일만 본다.

    2026-08-05 실측: MCP 서버가 아예 안 뜨면 로그 파일 자체가 안 생기는데,
    이전 기동의 낡은 '성공' 로그가 남아 있으면 합격으로 오판한다."""
    d = mcp_log_dir(workdir)
    files = sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime) if d.is_dir() else []
    if since is not None:
        files = [f for f in files if f.stat().st_mtime >= since]
        if not files:
            return "FAIL", ("설치 이후 MCP 로그 없음 — MCP 미기동이거나 동명 세션 충돌"
                            "(다른 기기의 같은 계정 세션 포함, 2026-08-10 실측)일 수 있음. "
                            "scripts/bot-restart.sh 로 재기동 후 verify 재실행, 반복되면 세션 이름 충돌 의심")
    if not files:
        return "WARN", f"판정 로그 없음(미기동 또는 동명 세션 충돌 — 다른 기기 포함): {d}"
    text = files[-1].read_text(encoding="utf-8", errors="ignore")
    if "Successfully connected" in text:
        return "OK", "MCP 연결 성공"
    if "Connection failed" in text:
        return "FAIL", "MCP 연결 실패 — 토큰 오입력·인텐트 미설정·초대 누락 확인"
    return "WARN", f"판정 로그 없음(미기동 또는 동명 세션 충돌 — 다른 기기 포함): {d}"

MCP_PROC_MARK = "claude-plugins-official/discord"

def _process_table_win():
    r = subprocess.run(
        ["pwsh", "-NoProfile", "-Command",
         "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine "
         "| ConvertTo-Json -Compress"],
        capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return []
    data = json.loads(r.stdout)
    if isinstance(data, dict):  # 프로세스 1개뿐이면 pwsh가 배열 대신 객체를 준다
        data = [data]
    table = []
    for row in data:
        table.append((row["ProcessId"], row["ParentProcessId"], row.get("CommandLine") or ""))
    return table

def _exclude_self_and_ancestors(table):
    """self·조상 프로세스를 결과에서 뺀다 — 실측 함정: 필터가 제 커맨드라인을
    매칭해 자멸한 사고(docs/spikes 함정 1, macOS `grep -v grep`과 동형 문제)."""
    by_pid = {pid: ppid for pid, ppid, _ in table}
    exclude = set()
    pid = os.getpid()
    while pid is not None and pid not in exclude:
        exclude.add(pid)
        pid = by_pid.get(pid)
    return [row for row in table if row[0] not in exclude]

def _process_table():
    """(pid, ppid, command) 목록 — HARNESS_FAKE_PS 가 있으면 그 스냅샷(테스트 시임,
    양 플랫폼 공통 포맷: "pid ppid command..." 줄 단위)."""
    fake = os.environ.get("HARNESS_FAKE_PS")
    if fake is not None:
        table = []
        for line in fake.splitlines():
            parts = line.split(None, 2)
            if len(parts) == 3:
                try:
                    table.append((int(parts[0]), int(parts[1]), parts[2]))
                except ValueError:
                    pass
        return table
    if IS_WIN:
        return _exclude_self_and_ancestors(_process_table_win())
    lines = subprocess.run(["ps", "-axo", "pid=,ppid=,command="],
                           capture_output=True, text=True).stdout.splitlines()
    table = []
    for line in lines:
        parts = line.split(None, 2)
        if len(parts) == 3:
            try:
                table.append((int(parts[0]), int(parts[1]), parts[2]))
            except ValueError:
                pass
    return table

def pid_alive(pid: int) -> bool:
    """os.kill(pid, 0)의 대체 — Windows에서 죽은 pid에도 성공 반환하는 결함이
    실측됐다(docs/spikes). 같은 프로세스 테이블에서 실존을 확인하며, 이 오판은
    플랫폼 무관한 결함이라 macOS 경로에도 함께 적용한다(ADR 결정)."""
    return any(p == pid for p, _, _ in _process_table())

def _pane_pid(session: str):
    """tmux 세션 첫 pane 의 pid. 세션 없으면 None. HARNESS_FAKE_PANES 시임 지원."""
    fake = os.environ.get("HARNESS_FAKE_PANES")
    if fake is not None:
        m = json.loads(fake)
        return int(m[session]) if session in m else None
    r = subprocess.run([find_tmux(), "list-panes", "-t", session, "-F", "#{pane_pid}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    for tok in r.stdout.split():
        return int(tok)
    return None

def _session_root_win(session: str):
    """세션 이름으로 claude 루트 pid를 찾는다 — tmux pane 대신 cmdline
    "-n <세션>" 매칭(결정 5). MCP stdio 서버는 claude.exe의 직계 자식으로
    뜬다(스파이크 실측)."""
    needle = f"-n {session}"
    for pid, _, cmd in _process_table():
        if not cmd or needle not in cmd:
            continue
        argv = _cmd_argv(cmd)
        if argv and Path(argv[0]).name.lower().startswith("claude"):
            return pid
    return None

def _tui_root_win(workdir: str):
    """codex TUI(orca 터미널)를 호스팅하는 pwsh 루트 pid.

    orca는 터미널→PID 매핑을 CLI로 안 준다(pane-mjs-design.md §9·§5.4 실측) —
    claude 봇처럼 cmdline에 `-n <세션>` 마커도 없다(codex는 세션명을 모른다).
    대신 orca가 터미널을 띄울 때 pwsh에 넘기는 `-EncodedCommand`(base64
    UTF-16LE)를 복호화하면 `bridge_win.py cmd_tui_up`이 그대로 심은
    `Set-Location -LiteralPath '<CODEX_WORKDIR>'; & ...` 리터럴이 남아있다 —
    그 문자열에 workdir가 포함된 pwsh를 루트로 삼는다(2026-09-02 실측)."""
    if not workdir:
        return None
    for pid, _, cmd in _process_table():
        if not cmd or "-EncodedCommand" not in cmd:
            continue
        argv = _cmd_argv(cmd)
        try:
            idx = next(i for i, a in enumerate(argv) if a.lower() == "-encodedcommand")
            b64 = argv[idx + 1]
        except (StopIteration, IndexError):
            continue
        try:
            decoded = base64.b64decode(b64).decode("utf-16-le", errors="ignore")
        except (ValueError, UnicodeDecodeError):
            continue
        if workdir in decoded:
            return pid
    return None

def session_procs(session: str, workdir: str = None):
    """세션 프로세스 트리의 (pid, command) 목록. 세션 없으면 None.
    HARNESS_FAKE_PANES 시임이 있으면 그걸 우선(플랫폼 무관 결정론적 테스트 경로) —
    실제 경로는 macOS=tmux pane(_pane_pid), Windows=cmdline 매칭(_session_root_win).
    workdir가 주어지면(코덱스 TUI 전용 호출) Windows 실경로는 `_tui_root_win`을
    쓴다 — codex는 `-n <세션>` 마커가 없어 `_session_root_win`으로 못 찾는다."""
    if os.environ.get("HARNESS_FAKE_PANES") is None and IS_WIN:
        root = _tui_root_win(workdir) if workdir else _session_root_win(session)
    else:
        root = _pane_pid(session)
    if root is None:
        return None
    table = _process_table()
    kids = {}
    for pid, ppid, _ in table:
        kids.setdefault(ppid, []).append(pid)
    ids, todo = {root}, [root]
    while todo:
        for c in kids.get(todo.pop(), []):
            if c not in ids:
                ids.add(c)
                todo.append(c)
    return [(pid, cmd) for pid, ppid, cmd in table if pid in ids]

def mcp_server_alive(session: str) -> bool:
    """봇 tmux 세션 자손에 discord 플러그인 MCP 서버 프로세스가 실존하는가.

    3차 실측(2026-08-05): 로그 판정만으로는 진단용 `claude mcp list`가 남긴
    신선한 성공 로그가 거짓 합격을 만든다 — 프로세스 실존을 함께 요구한다."""
    procs = session_procs(session)
    return bool(procs) and any(MCP_PROC_MARK in cmd for _, cmd in procs)

def _cmd_argv(cmdline: str) -> list:
    """cmdline을 실제 인자 목록으로 쪼갠다. Windows Get-CimInstance CommandLine은
    따옴표 포함 경로를 그대로 준다("C:\\Program Files\\...") — naive split()은
    공백에서 깨진다(실측). CommandLineToArgvW로 정확히 파싱; macOS ps 출력은
    따옴표가 없어 naive split으로 충분하다."""
    if not cmdline:
        return []
    if not IS_WIN:
        return cmdline.split()
    shell32 = ctypes.windll.shell32
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argc = ctypes.c_int()
    argv_p = shell32.CommandLineToArgvW(cmdline, ctypes.byref(argc))
    if not argv_p:
        return []
    try:
        return [argv_p[i] for i in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv_p)

def _is_codex_cmd(cmdline: str) -> bool:
    """브리지(codex-discord treeHasCodex)와 동일 기준 — npm 배포판은 codex가
    `#!/usr/bin/env node` 런처라 argv0이 node로 잡힌다(2026-08-05 실측)."""
    parts = _cmd_argv(cmdline)
    base = lambda p: Path(p).name if p else ""
    if base(parts[0] if parts else "").startswith("codex"):
        return True
    return (base(parts[0] if parts else "") in ("node", "bun")
            and base(parts[1] if len(parts) > 1 else "").startswith("codex"))

def _rollout_exists(workdir: str) -> bool:
    """cwd 일치 codex 롤아웃 파일 존재 여부 — 브리지의 세션 특정 검출원.
    codex v0.146.0 기본 설정은 세션 UUID를 화면에 표시하지 않아(3차 실측)
    브리지가 롤아웃 session_meta.cwd 로 세션을 특정한다.

    plan 문서는 이 함수가 "이미 이식성 있음"이라 적었으나 그건 json.loads
    비교(경로 구분자 무관)에 대한 얘기였다 — 루트 자체가 `~/.codex`로
    고정돼 있었던 건 별개 문제. 2026-09-01 codex-discord 검증에서 실측:
    Orca가 `CODEX_HOME`을 자체 관리 홈으로 리다이렉트하는 환경(이 개발
    머신 포함)에서는 `~/.codex`가 아예 갱신되지 않아 롤아웃을 영원히 못
    찾는다(codex-discord `rollout.mjs` 커밋 db80d88과 동형 수정)."""
    codex_home = os.environ.get("CODEX_HOME")
    root = Path(codex_home) / "sessions" if codex_home else home() / ".codex/sessions"
    if not root.is_dir():
        return False
    for f in sorted(root.rglob("rollout-*.jsonl"), reverse=True):
        try:
            with f.open(encoding="utf-8", errors="ignore") as fh:
                meta = json.loads(fh.readline())
            if meta.get("payload", {}).get("cwd") == workdir:
                return True
        except (OSError, ValueError):
            continue
    return False

def judge_codex_tui():
    """코덱스 TUI 판정 — TUI_PANE 미구성이면 None. 세션·pane이 있어도 codex가
    죽어 있으면 브리지가 호명을 거부한다(3차 실측). tui-up.sh 는 멱등."""
    if not (bridge_repo() / ".env").exists():
        return None
    env = parse_env(bridge_repo() / ".env")
    tui_pane = env.get("TUI_PANE")
    if not tui_pane:
        return None
    tui_sess = tui_pane.split(":", 1)[0]
    workdir = env.get("CODEX_WORKDIR")
    procs = session_procs(tui_sess, workdir=workdir)
    fix = (f"python {bridge_repo()}/scripts/bridge_win.py tui-up 로 재기동 후 verify 재실행"
           if IS_WIN else f"bash {bridge_repo()}/scripts/tui-up.sh 로 재기동 후 verify 재실행")
    if procs is None:
        return "FAIL", f"코덱스 TUI 세션({tui_sess}) 없음 — {fix}"
    if not any(_is_codex_cmd(cmd) for _, cmd in procs):
        return "FAIL", f"코덱스 TUI pane({tui_pane})에 codex 없음(종료됨) — {fix}"
    if workdir and not _rollout_exists(workdir):
        return "FAIL", (f"코덱스 TUI({tui_pane}): 세션 롤아웃 없음(cwd={workdir} 일치 "
                        f"파일 부재) — 브리지가 세션을 특정하지 못해 호명이 실패한다. {fix}")
    return "OK", f"코덱스 TUI({tui_pane}) codex 가동 · 세션 롤아웃 확인"

def judge_bridge(logname: str):
    p = bridge_repo() / "logs" / logname
    if p.exists() and "로그인:" in p.read_text(encoding="utf-8", errors="ignore"):
        return "OK", f"브리지 로그인 확인({logname})"
    return "FAIL", f"브리지 로그인 없음 — {p} 확인"

def cmd_doctor(a) -> None:
    fails = 0
    def rep(level, msg):
        nonlocal fails
        if level == "FAIL":
            fails += 1
        print(f"[{level}] {msg}")
    pn = pins()
    st = load_state()
    for name in REPO_NAMES:
        got = st.get("repos", {}).get(name)
        pin = pn["repos"][name]["ref"]
        if not got:
            rep("WARN", f"{name}: fetch 기록 없음 — harnessctl.py fetch 필요")
            continue
        if got["ref"] != pin:
            rep("WARN", f"{name}: 설치 {got['ref']} ≠ 검증 조합 {pin} — 설치기·부품 버전 어긋남")
            continue
        cur = run_git(["rev-parse", "HEAD"], cwd=repos_dir() / name).stdout.strip()
        if cur and cur != got["commit"]:
            rep("WARN", f"{name}: HEAD가 기록과 다름(임의 pull?) — 검증 조합 이탈")
        else:
            rep("OK", f"{name}: {got['ref']}")
    for pname in PLUGIN_NAMES:
        v = installed_plugin_version(pname)
        need = pn["plugins"][pname]["ref"]
        if v is None:
            rep("WARN", f"플러그인 {pname} 미설치 — harnessctl.py plugins 필요")
        elif version_tuple(v) < version_tuple(need):
            rep("WARN", f"플러그인 {pname} {v} < 호환 최소 {need}")
        else:
            rep("OK", f"플러그인 {pname} {v}")
    for p in (bridge_repo() / "scripts/install.sh", bridge_repo() / "scripts/uninstall.sh",
              coach_repo() / "scripts/install.sh", coach_repo() / "scripts/uninstall.sh",
              harness_repo() / "scripts/install-autostart.sh"):
        if not p.exists():
            rep("WARN", f"위임 계약 파일 없음: {p}")
        elif not os.access(p, os.X_OK):
            rep("WARN", f"위임 계약 실행권한 없음: {p}")
        else:
            rep("OK", f"위임 계약: {p.parent.parent.name}/{p.parent.name}/{p.name}")
    mp = harness_repo() / "install/overlay-manifest.json"
    if not mp.exists():
        rep("WARN", f"오버레이 manifest 없음: {mp}")
    else:
        sv = json.loads(mp.read_text(encoding="utf-8")).get("schema_version")
        rep("OK" if sv == SCHEMA_VERSION else "FAIL",
            f"manifest schema_version {sv}" + ("" if sv == SCHEMA_VERSION else f" ≠ {SCHEMA_VERSION} — 설치기 업데이트 필요"))
    wd = getattr(a, "work_dir", None) or st.get("work_dir")
    if wd:
        work = Path(wd).expanduser()
        rep("OK" if (work / ".env").exists() else "WARN",
            f"페어링(.env): {'있음' if (work / '.env').exists() else '없음 — pair 필요'}")
        if IS_WIN:
            registered = schtasks_registered(WIN_AUTOSTART_TASK)
            rep("OK" if registered else "WARN",
                f"자동 기동(schtasks {WIN_AUTOSTART_TASK}): {'등록됨' if registered else '없음 — autostart-install 필요'}")
            sessions = bot_sessions(work)
            for label, sess in (("오케스트레이터", sessions["orch"]), ("수다 클로드", sessions["chat"])):
                alive = session_procs(sess) is not None
                rep("OK" if alive else "WARN", f"세션 {label}({sess}) {'생존' if alive else '없음'}")
        else:
            for label, p in ((ORCH_PLIST_LABEL, home() / f"Library/LaunchAgents/{ORCH_PLIST_LABEL}.plist"),
                             (CHAT_PLIST_LABEL, chat_plist_path())):
                rep("OK" if p.exists() else "WARN", f"plist {label}: {'있음' if p.exists() else '없음'}")
            for sess in ("orchestrator", CHAT_SESSION):
                alive = subprocess.run([find_tmux(), "has-session", "-t", sess],
                                       capture_output=True).returncode == 0
                rep("OK" if alive else "WARN", f"tmux 세션 {sess} {'생존' if alive else '없음'}")
    sys.exit(1 if fails else 0)

def cmd_remove(a) -> None:
    st = load_state()
    work = resolve_work_dir(a)
    warns = 0
    def warn(msg):
        nonlocal warns
        warns += 1
        print(f"[WARN] {msg}")
    if IS_WIN:
        if schtasks_registered(WIN_AUTOSTART_TASK):
            subprocess.run(["schtasks", "/delete", "/tn", WIN_AUTOSTART_TASK, "/f"],
                           capture_output=True)
            print(f"자동 기동 해제: {WIN_AUTOSTART_TASK}")
        # 실행 중인 봇 세션은 강제 종료하지 않는다 — /exit 없는 강제 종료는 유령
        # 리스를 만든다(discord-harness-installer 2026-08-06 실측, ADR-0001 근거).
        # bot_win.py restart가 정상 종료 경로를 갖고 있으니 그쪽으로 유도한다.
        print("[SKIP] 실행 중인 봇 세션은 자동 종료하지 않음(정상 종료 보장) — "
             "orca terminal에서 각 세션에 /exit 입력 후 닫거나 bot_win.py restart 사용")
    else:
        tmux = find_tmux()
        for sess in ("orchestrator", CHAT_SESSION):
            subprocess.run([tmux, "kill-session", "-t", sess], capture_output=True)
        for p in (home() / f"Library/LaunchAgents/{ORCH_PLIST_LABEL}.plist", chat_plist_path()):
            if p.exists():
                p.unlink()
                print(f"plist 제거: {p}")
    for script, cwd in ((bridge_repo() / "scripts/uninstall.sh", bridge_repo()),
                        (coach_repo() / "scripts/uninstall.sh", coach_repo())):
        if script.exists():
            r = subprocess.run([bash_bin(), script.as_posix()], cwd=cwd)  # MSYS 백슬래시 파싱 회피
            if r.returncode != 0:
                warn(f"제거 스크립트 실패(exit {r.returncode}): {script} — 수동 확인 필요")
        else:
            warn(f"제거 스크립트 없음(수동 확인 필요): {script}")
    for rel, saved in sorted(st.get("overlay", {}).items()):
        p = work / rel
        if not p.exists():
            continue
        if sha256(p) == saved:
            p.unlink()
            print(f"제거: {p}")
        else:
            warn(f"사용자 수정 감지 — 보존: {p}")
    for rel, entry in sorted(st.get("settings_added", {}).items()):
        p = work / rel
        if not p.exists():
            continue
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            warn(f"권한 파일 파싱 실패 — 보존: {p}")
            continue
        if entry.get("eams"):
            cur.pop("enableAllProjectMcpServers", None)
        if entry.get("statusline"):
            cur.pop("statusLine", None)
        if entry.get("mode"):
            cur.get("permissions", {}).pop("defaultMode", None)
        allow = cur.get("permissions", {}).get("allow", [])
        for perm in entry.get("allow", []):
            if perm in allow:
                allow.remove(perm)
        if cur.get("permissions", {}).get("allow") == []:
            cur["permissions"].pop("allow")
        if cur.get("permissions") == {}:
            cur.pop("permissions")
        if entry.get("created") and not cur:
            p.unlink()
            try:
                p.parent.rmdir()
            except OSError:
                pass
            print(f"권한 파일 제거: {p}")
        else:
            p.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"권한 사전 승인 회수: {p}")
    for line in remove_claude_block(work / "CLAUDE.md"):
        print(line)
    mcp_path = work / ".mcp.json"
    if st.get("mcp_added") and mcp_path.exists():
        cur = json.loads(mcp_path.read_text(encoding="utf-8"))
        for k in st["mcp_added"]:
            cur.get("mcpServers", {}).pop(k, None)
        mcp_path.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f".mcp.json 항목 제거: {st['mcp_added']}")
    for rel, lines in st.get("lines_added", {}).items():
        p = work / rel
        if not p.exists():
            continue
        cur = p.read_text(encoding="utf-8").splitlines()
        removed = False
        for line in lines:
            if line in cur:
                cur.remove(line)
                removed = True
        if removed:
            p.write_text("\n".join(cur) + ("\n" if cur else ""), encoding="utf-8")
            print(f"줄 제거: {p} -= {len(lines)}줄")
    if repos_dir().exists():
        rmtree_force(repos_dir())
        print(f"소스 저장소 제거: {repos_dir()}")
    if warns:
        print(f"[WARN] {warns}건 미완 — 상태 보존({state_path()}). 재실행하면 이어서 제거한다")
    elif state_path().exists():
        state_path().unlink()
    print("제거 완료 — 보존: .env·.discord-state·chat/(사용자 수정분)·tasks/·SESSION.md·~/.config/usage-coach/")

def cmd_verify(a) -> None:
    work = resolve_work_dir(a)
    fails = 0
    def rep(level, msg):
        nonlocal fails
        if level == "FAIL":
            fails += 1
        print(f"[{level}] {msg}")
    steps = load_state().get("steps", {})
    since = None
    for key in ("pair", "install-delegate"):
        if steps.get(key):
            ts = datetime.fromisoformat(steps[key]).timestamp()
            since = ts if since is None else max(since, ts)
    sessions = bot_sessions(work)
    bots = (("오케스트레이터", sessions["orch"], work),
            ("수다 클로드", sessions["chat"], work / "chat"))
    wait = getattr(a, "wait", 0) or 0
    if wait:
        # bot-up.sh 직렬화(락 대기 300초 + 연결 판정 240초) 중 조기 FAIL 방지 —
        # 두 봇의 로그·프로세스 판정이 모두 OK가 될 때까지 상한 내 폴링
        print(f"[..] 봇 연결 안정화 대기(최대 {wait}초)")
        deadline = time.time() + wait
        while time.time() < deadline:
            # TUI 기동은 launchd 비동기(tui-up 최대 360초)라 install 직후엔 아직
            # 부팅 중일 수 있다 — 대기 조건에 포함 (회신4 제안 3)
            tui = judge_codex_tui()
            if (all(judge_mcp(wd, since)[0] == "OK" and mcp_server_alive(sess)
                    for _, sess, wd in bots)
                    and (tui is None or tui[0] == "OK")):
                break
            time.sleep(min(3, max(0.5, deadline - time.time())))
    for label, sess, wd in bots:
        lvl, msg = judge_mcp(wd, since)
        if lvl == "OK" and not mcp_server_alive(sess):
            lvl, msg = "FAIL", ("성공 로그는 있으나 MCP 서버 프로세스 없음 — 다른 세션"
                                "(claude mcp list 등)의 로그일 수 있음. "
                                "scripts/bot-restart.sh 로 재기동 후 verify 재실행")
        rep(lvl, f"{label}: {msg}")
    bridge_specs = [("코덱스", "daemon.log", "data/daemon.pid")]
    if (bridge_repo() / ".env.gemini").exists():
        bridge_specs.append(("제미나이", "daemon-gemini.log", "data-gemini/daemon.pid"))
    else:
        rep("WARN", "제미나이: 브리지 .env.gemini 없음 — 미구성으로 건너뜀")
    for label, logname, pidrel in bridge_specs:
        lvl, msg = judge_bridge(logname)  # 로그 파일 읽기라 플랫폼 무관(B2-6)
        rep(lvl, f"{label}: {msg}")
        pid_p = bridge_repo() / pidrel
        alive = False
        if pid_p.exists():
            try:
                alive = pid_alive(int(pid_p.read_text(encoding="utf-8").split()[0]))
            except ValueError:
                pass
        rep("OK" if alive else "WARN",
            f"{label} 데몬 {'생존' if alive else '죽음/미기동'}: {pid_p}")
    # Windows는 _tui_root_win(ptyId 대신 orca -EncodedCommand 복호화로 workdir
    # 매칭)이 루트를 찾는다(Phase 3, T3-1) — session_procs가 플랫폼 분기를
    # 안으로 감춰서 여기는 macOS와 동일 호출 하나로 충분하다(T3-2).
    tui = judge_codex_tui()
    if tui:
        rep(*tui)
    for sess in (sessions["orch"], sessions["chat"]):
        procs = session_procs(sess)
        if procs is None:
            rep("WARN", f"세션 {sess} 없음")
        elif any(Path(_cmd_argv(cmd)[0]).name.startswith("claude")
                for _, cmd in procs if _cmd_argv(cmd)):
            rep("OK", f"세션 {sess} claude 가동")
        else:
            # 세션 존재 ≠ 봇 가동 — bot-up 락 대기 중이면 pane/터미널이 비어 있다 (3차 실측)
            rep("WARN", f"세션 {sess}: 세션은 있으나 claude 프로세스 없음(기동 대기/실패)")
    if IS_WIN:
        registered = schtasks_registered(WIN_AUTOSTART_TASK)
        rep("OK" if registered else "WARN",
            f"자동 기동(schtasks {WIN_AUTOSTART_TASK}): {'등록됨' if registered else '없음'}")
    else:
        for label, p in ((ORCH_PLIST_LABEL, home() / f"Library/LaunchAgents/{ORCH_PLIST_LABEL}.plist"),
                         (CHAT_PLIST_LABEL, chat_plist_path())):
            rep("OK" if p.exists() else "WARN", f"plist {label}: {'있음' if p.exists() else '없음'}")
    if not a.skip_webhook:
        cfg = home() / ".config/usage-coach/discord.json"
        if not cfg.exists():
            rep("WARN", f"웹훅 설정 없음: {cfg}")
        else:
            import urllib.request
            url = json.loads(cfg.read_text(encoding="utf-8")).get("webhook_url", "")
            try:
                req = urllib.request.Request(
                    url, data=json.dumps({"content": "harness-installer verify: 웹훅 OK"}).encode(),
                    headers={"Content-Type": "application/json",
                             "User-Agent": "usage-coach-dash"})
                urllib.request.urlopen(req, timeout=10)
                rep("OK", "웹훅 시험 발사 성공")
            except Exception as e:
                rep("FAIL", f"웹훅 발사 실패: {e}")
    if not fails:
        st = load_state(); st["steps"]["verify"] = now(); save_state(st)
    sys.exit(1 if fails else 0)

def cmd_install(a) -> None:
    st = load_state()
    work = Path(a.work_dir).expanduser() if a.work_dir else resolve_work_dir(a)
    st["work_dir"] = str(work)
    out = []
    if a.phase in ("overlay", "all"):
        out += apply_overlay(work, st)
        out += apply_seeds(work, st)
        out += write_bot_settings(work, st)
    if a.phase in ("delegate", "all"):
        for line in write_bridge_envs(work):
            print(line)
        if IS_WIN:
            bridge_script = bridge_repo() / "scripts/bridge_win.py"
            if bridge_script.exists():
                delegate([sys.executable, bridge_script, "install"], bridge_repo(),
                         a.dry_run, str(bridge_repo() / "logs"))
            else:
                print(f"[SKIP] 브리지(코덱스) 설치 — {bridge_script} 없음 (pins.json codex-discord ref 확인)")
        else:
            delegate([bash_bin(), bridge_repo() / "scripts/install.sh"], bridge_repo(),
                     a.dry_run, str(bridge_repo() / "logs"))
        if a.dashboard and IS_WIN:
            dash_script = coach_repo() / "scripts/dash_win.py"
            if dash_script.exists():
                delegate([sys.executable, dash_script, "install"],
                         coach_repo(), a.dry_run, f"schtasks /query /tn {WIN_DASHBOARD_TASK}")
            else:
                print(f"[SKIP] 대시보드(usage-coach) 설치 — {dash_script} 없음"
                      "(pins.json usage-coach ref 확인)")
        elif a.dashboard:
            delegate([bash_bin(), coach_repo() / "scripts/install.sh"], coach_repo(),
                     a.dry_run, "~/.config/usage-coach/")
        if a.autostart and IS_WIN:
            # overlay 단계가 work/scripts/bot_win.py를 이미 복사해 뒀다(manifest 등록,
            # ADR-0004). cwd=work라야 bot_win.py가 이 폴더의 bots.json을 정본으로 잡는다.
            delegate([sys.executable, work / "scripts/bot_win.py", "autostart-install"],
                     work, a.dry_run, f"schtasks /query /tn {WIN_AUTOSTART_TASK}")
        elif a.autostart:
            delegate([bash_bin(), work / "scripts/install-autostart.sh"], work,
                     a.dry_run, "launchctl print gui/$(id -u)/" + ORCH_PLIST_LABEL)
            if a.dry_run:
                print(f"위임(dry-run): plist 생성 예정 — {chat_plist_path()}")
            else:
                for line in write_chat_plist(work):
                    print(line)
    for line in out:
        print(line)
    if not a.dry_run:
        st["steps"][f"install-{a.phase}"] = now()
    save_state(st)

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    fl = sub.add_parser("preflight", help="전제 도구 점검(읽기 전용)")
    fl.add_argument("--work-dir", help="Windows: git 레포 검사 대상(기본 cwd)")
    fl.set_defaults(fn=cmd_preflight)
    fp = sub.add_parser("fetch", help="정본 3레포 clone/pull (기본: 검증 조합 핀)")
    fp.add_argument("--latest", action="store_true")
    fp.set_defaults(fn=cmd_fetch)
    pp = sub.add_parser("plugins", help="starter·folder-bot 플러그인 직접 설치")
    pp.add_argument("--host", choices=("claude", "codex"), default="claude")
    pp.add_argument("--dry-run", action="store_true")
    pp.set_defaults(fn=cmd_plugins)
    rp = sub.add_parser("pair", help="토큰 파일 수령 → .env 조립(0600) → 토큰 파일 삭제")
    rp.add_argument("--work-dir", required=True)
    rp.add_argument("--work-channel-id", required=True)
    rp.add_argument("--chat-channel-id", required=True)
    rp.add_argument("--approver-user-id", required=True)
    rp.add_argument("--webhook-url-file")
    rp.add_argument("--force", action="store_true")
    rp.set_defaults(fn=cmd_pair)
    ip = sub.add_parser("install", help="오버레이 적용 + 위임 설치 호출")
    ip.add_argument("--work-dir")
    ip.add_argument("--phase", choices=("overlay", "delegate", "all"), default="all")
    ip.add_argument("--dashboard", action="store_true")
    ip.add_argument("--autostart", action="store_true")
    ip.add_argument("--dry-run", action="store_true")
    ip.set_defaults(fn=cmd_install)
    vp = sub.add_parser("verify", help="기동 후 연결 판정(판정 소스 2종, 읽기 전용)")
    vp.add_argument("--work-dir")
    vp.add_argument("--skip-webhook", action="store_true")
    vp.add_argument("--wait", type=int, default=0,
                    help="MCP 연결 안정화 대기 상한(초) — bot-up 직렬화 최대 540초 고려")
    vp.set_defaults(fn=cmd_verify)
    dp = sub.add_parser("doctor", help="종합 점검 + 버전 호환 + 위임 계약 방어(읽기 전용)")
    dp.add_argument("--work-dir")
    dp.set_defaults(fn=cmd_doctor)
    xp = sub.add_parser("remove", help="설치기 소유분만 제거(starter·folder-bot 산출물 제외, 사용자 데이터 보존)")
    xp.add_argument("--work-dir")
    xp.set_defaults(fn=cmd_remove)
    a = p.parse_args()
    a.fn(a)

if __name__ == "__main__":
    main()
