import json, os, plistlib, re, shutil, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import pytest

HARNESSCTL = (Path(__file__).parent.parent
              / "plugins/harness-installer/skills/configure-harness/generator/harnessctl.py")
PINS = json.loads((HARNESSCTL.parent / "pins.json").read_text(encoding="utf-8"))

def run(home_dir, *args, env_extra=None):
    env = dict(os.environ, HOME=str(home_dir))
    if sys.platform == "win32":
        env["USERPROFILE"] = str(home_dir)
        env["LOCALAPPDATA"] = str(home_dir)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(HARNESSCTL), *args],
                          capture_output=True, text=True, env=env,
                          encoding="utf-8", errors="replace")

STUB = "#!/bin/bash\necho stub-ok\n"
PY_STUB = "print('stub-ok')\n"  # bot_win.py 자리 — 인자 무관 항상 exit 0(실제 schtasks 미호출)
MANIFEST = {
    "schema_version": 1,
    "overlay": [
        {"src": "scripts/bot-up.sh", "dst": "scripts/bot-up.sh", "mode": "755"},
        {"src": "scripts/bot-restart.sh", "dst": "scripts/bot-restart.sh", "mode": "755"},
        {"src": "scripts/post-as.sh", "dst": "scripts/post-as.sh", "mode": "755"},
        {"src": "scripts/new-thread.sh", "dst": "scripts/new-thread.sh", "mode": "755"},
        {"src": "scripts/install-autostart.sh", "dst": "scripts/install-autostart.sh", "mode": "755"},
        {"src": "scripts/bot_win.py", "dst": "scripts/bot_win.py", "mode": "755"},
        {"src": ".env.example", "dst": ".env.example", "mode": "644"},
        {"src": ".mcp.json", "dst": ".mcp.json", "mode": "644", "merge": "json-mcp-servers"},
        {"src": "install/gitignore-discord", "dst": ".gitignore", "mode": "644", "merge": "append-lines"},
    ],
    "seeds": [{"src": "install/chat-CLAUDE.md", "dst": "chat/CLAUDE.md"}],
    "claude_block": {"src": "CLAUDE.md"},
}

def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))

def _make_repo(base, name, files, tag):
    d = base / name
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        if rel.endswith(".sh"):
            p.chmod(0o755)
    _git(d, "init", "-q", "-b", "main")
    _git(d, "add", "-A")
    _git(d, "commit", "-qm", "init")
    _git(d, "tag", tag)
    return d

def make_fixture_repos(tmp_path):
    base = tmp_path / "origin"
    base.mkdir(exist_ok=True)
    harness_files = {
        "scripts/bot-up.sh": STUB, "scripts/bot-restart.sh": STUB,
        "scripts/post-as.sh": STUB, "scripts/new-thread.sh": STUB,
        "scripts/install-autostart.sh": STUB,
        "scripts/bot_win.py": PY_STUB,
        ".env.example": "WORK_CHANNEL_ID=\nCHAT_CHANNEL_ID=\n",
        ".mcp.json": json.dumps({"mcpServers": {"codex": {"type": "stdio", "command": "codex",
                                                          "args": ["mcp-server"], "env": {}}}}, indent=2),
        "CLAUDE.md": ("# 하네스\n\n<!-- discord-multiagent:start -->\n## Discord 운영\n"
                      "승인 판정·미러 규칙(정본 본문).\n<!-- discord-multiagent:end -->\n"),
        "install/overlay-manifest.json": json.dumps(MANIFEST, indent=2),
        "install/chat-CLAUDE.md": "# 수다 채널 클로드\n호명될 때만 응답.\n",
        "install/gitignore-discord": ("# discord 하네스 비밀 — 커밋 금지 (harness-installer overlay)\n"
                                      ".env\n.discord-state/\n.bot-token-*\n.webhook-url\n"),
    }
    bridge_files = {
        "scripts/install.sh": STUB, "scripts/uninstall.sh": STUB,
        "src/index.mjs": "// stub\n",
    }
    coach_files = {
        "scripts/install.sh": STUB, "scripts/uninstall.sh": STUB,
        "scripts/dash_win.py": PY_STUB,
        "discord_dash.py": "# stub\n",
    }
    for name, files in (("discord-multiagent", harness_files),
                        ("codex-discord", bridge_files), ("usage-coach", coach_files)):
        _make_repo(base, name, files, PINS["repos"][name]["ref"])
    return base

def fetched(tmp_path):
    base = make_fixture_repos(tmp_path)
    r = run(tmp_path, "fetch", env_extra={"HARNESS_REPO_BASE": str(base)})
    assert r.returncode == 0, r.stdout + r.stderr
    return base

# Windows에서 preflight는 --work-dir 대상의 git 레포 여부도 검사한다(ADR-0005 결정 8).
# tmp_path는 기본적으로 git 레포가 아니므로 Windows 테스트는 먼저 init한다.
def _win_preflight_repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    return ["--work-dir", str(tmp_path)]

def test_preflight_fails_on_bare_env(tmp_path):
    # tmp HOME 에는 discord 플러그인 캐시가 없다 → 최소 1개 FAIL → exit 1
    extra = _win_preflight_repo(tmp_path) if sys.platform == "win32" else []
    r = run(tmp_path, "preflight", *extra)
    assert r.returncode == 1
    assert "[FAIL]" in r.stdout and "discord 플러그인" in r.stdout

def test_preflight_reports_tools(tmp_path):
    r = run(tmp_path, "preflight")
    session_tool = "orca" if sys.platform == "win32" else "tmux"
    assert "[OK] git" in r.stdout and session_tool in r.stdout and "claude" in r.stdout

def test_preflight_ok_when_all_present(tmp_path):
    (tmp_path / ".claude/plugins/cache/claude-plugins-official/discord").mkdir(parents=True)
    extra = _win_preflight_repo(tmp_path) if sys.platform == "win32" else []
    r = run(tmp_path, "preflight", *extra)
    # 개발 머신 전제: git/orca(또는 tmux)/pwsh/node/bun/claude/codex 는 PATH 에 있다
    assert r.returncode == 0, r.stdout + r.stderr

def test_preflight_fails_without_bun(tmp_path):
    # discord 플러그인 MCP 실행기(bun) 부재는 8단계가 아니라 1단계에서 잡혀야 한다
    (tmp_path / ".claude/plugins/cache/claude-plugins-official/discord").mkdir(parents=True)
    bun_dir = os.path.dirname(shutil.which("bun"))
    path = os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if p != bun_dir)
    extra = _win_preflight_repo(tmp_path) if sys.platform == "win32" else []
    r = run(tmp_path, "preflight", *extra, env_extra={"PATH": path})
    assert r.returncode == 1
    assert "[FAIL] bun" in r.stdout and "bun.sh" in r.stdout

def test_preflight_win_fails_on_non_git_dir(tmp_path):
    if sys.platform != "win32":
        pytest.skip("Windows 전용 검사(ADR-0005 결정 8)")
    (tmp_path / ".claude/plugins/cache/claude-plugins-official/discord").mkdir(parents=True)
    r = run(tmp_path, "preflight", "--work-dir", str(tmp_path))
    assert r.returncode == 1
    assert "[FAIL] git 레포 아님" in r.stdout

def test_fetch_checks_out_pin_and_records(tmp_path):
    fetched(tmp_path)
    st = json.loads((tmp_path / ".config/discord-harness/state.json").read_text(encoding="utf-8"))
    for name in ("discord-multiagent", "codex-discord", "usage-coach"):
        assert (tmp_path / ".local/share/discord-harness/repos" / name / ".git").exists()
        assert st["repos"][name]["ref"] == PINS["repos"][name]["ref"]
        assert len(st["repos"][name]["commit"]) == 40
    assert st["steps"]["fetch"]

def test_fetch_idempotent(tmp_path):
    base = fetched(tmp_path)
    r = run(tmp_path, "fetch", env_extra={"HARNESS_REPO_BASE": str(base)})
    assert r.returncode == 0, r.stdout + r.stderr

def test_fetch_missing_pin_tag_fails_with_hint(tmp_path):
    base = make_fixture_repos(tmp_path)
    _git(base / "usage-coach", "tag", "-d", PINS["repos"]["usage-coach"]["ref"])
    r = run(tmp_path, "fetch", env_extra={"HARNESS_REPO_BASE": str(base)})
    assert r.returncode != 0
    assert "핀" in r.stderr and "usage-coach" in r.stderr

def test_plugins_dry_run_prints_commands(tmp_path):
    r = run(tmp_path, "plugins", "--dry-run")
    assert r.returncode == 0
    starter_owner = PINS["plugins"]["multi-agent-starter"]["owner"]
    folder_owner = PINS["plugins"]["folder-bot"]["owner"]
    assert f"claude plugin marketplace add {starter_owner}/multi-agent-starter" in r.stdout
    assert "claude plugin install multi-agent-starter@multi-agent-starter" in r.stdout
    assert f"claude plugin marketplace add {folder_owner}/folder-bot" in r.stdout
    assert "claude plugin install folder-bot@folder-bot" in r.stdout

def test_plugins_codex_host(tmp_path):
    r = run(tmp_path, "plugins", "--host", "codex", "--dry-run")
    folder_owner = PINS["plugins"]["folder-bot"]["owner"]
    assert f"codex plugin marketplace add {folder_owner}/folder-bot" in r.stdout

def test_plugins_failure_prints_manual_fallback(tmp_path):
    # PATH 를 비워 claude 실행 자체가 불가능한 상황 → 수동 폴백 안내 + exit 1
    r = run(tmp_path, "plugins", env_extra={"PATH": "/usr/bin:/bin"})
    assert r.returncode == 1
    assert "수동 폴백" in r.stdout

def _token_files(work):
    for role in ("orch", "claude", "codex", "gemini"):
        (work / f".bot-token-{role}").write_text(f"tok-{role}\n", encoding="utf-8")

def _pair(tmp_path, work, *extra):
    return run(tmp_path, "pair", "--work-dir", str(work),
               "--work-channel-id", "111", "--chat-channel-id", "222",
               "--approver-user-id", "999", *extra)

def test_pair_assembles_env_and_state_dirs(tmp_path):
    work = tmp_path / "work"; work.mkdir()
    _token_files(work)
    r = _pair(tmp_path, work)
    assert r.returncode == 0, r.stderr
    env = (work / ".env").read_text(encoding="utf-8")
    assert "WORK_CHANNEL_ID=111\n" in env and "CHAT_CHANNEL_ID=222\n" in env
    assert "APPROVER_USER_ID=999\n" in env and "ORCH_BOT_TOKEN=tok-orch\n" in env
    assert "CLAUDE_BOT_TOKEN=tok-claude\n" in env and "GEMINI_BOT_TOKEN=tok-gemini\n" in env
    if sys.platform == "win32":
        # chmod는 Windows에서 무시된다(스파이크 실측) — icacls 상속 제거 + 현재
        # 사용자 단독 허용(ADR 결정 10)을 icacls 출력으로 직접 확인한다. 상속분(I)
        # 없이 사용자 1인만 남아야 한다.
        icacls = subprocess.run(["icacls", str(work / ".env")], capture_output=True, text=True)
        user = os.environ.get("USERNAME", "")
        acl_lines = [l for l in icacls.stdout.splitlines() if ":(" in l]
        assert len(acl_lines) == 1 and user in acl_lines[0] and "(F)" in acl_lines[0], icacls.stdout
        assert "(I)" not in acl_lines[0]
    else:
        assert oct((work / ".env").stat().st_mode)[-3:] == "600"
    orch = json.loads((work / ".discord-state/access.json").read_text(encoding="utf-8"))
    assert orch["groups"]["111"]["requireMention"] is False
    assert (work / ".discord-state/.env").read_text(encoding="utf-8") == "DISCORD_BOT_TOKEN=tok-orch\n"
    chat = json.loads((work / "chat/.discord-state/access.json").read_text(encoding="utf-8"))
    assert chat["groups"]["222"]["requireMention"] is True
    assert (work / "chat/.discord-state/inbox").is_dir()
    for role in ("orch", "claude", "codex", "gemini"):
        assert not (work / f".bot-token-{role}").exists()   # 토큰 파일 즉시 삭제
    assert "tok-orch" not in r.stdout                        # 비밀 stdout 금지

def test_pair_refuses_overwrite_without_force(tmp_path):
    work = tmp_path / "work"; work.mkdir()
    _token_files(work)
    assert _pair(tmp_path, work).returncode == 0
    _token_files(work)
    r = _pair(tmp_path, work)
    assert r.returncode != 0
    assert "tok-orch" in (work / ".env").read_text(encoding="utf-8")   # 기존 보존
    _token_files(work)
    assert _pair(tmp_path, work, "--force").returncode == 0

def test_pair_webhook_file(tmp_path):
    work = tmp_path / "work"; work.mkdir()
    _token_files(work)
    wf = work / ".webhook-url"; wf.write_text("https://example.invalid/hook\n", encoding="utf-8")
    r = _pair(tmp_path, work, "--webhook-url-file", str(wf))
    assert r.returncode == 0, r.stderr
    cfg = json.loads((tmp_path / ".config/usage-coach/discord.json").read_text(encoding="utf-8"))
    assert cfg["webhook_url"] == "https://example.invalid/hook"
    assert not wf.exists()
    # 대시보드 "봇 세션" 카드가 이 설치를 가리켜야 한다 (기본값 = 저자 프로덕션 경로)
    repos = tmp_path / ".local/share/discord-harness/repos/codex-discord"
    assert cfg["bridges"][0]["dir"] == str(repos / "data")
    assert cfg["bridges"][1]["env"] == str(repos / ".env.gemini")
    assert cfg["claude_bots"][0]["cwd"] == str(work)
    assert cfg["claude_bots"][1]["cwd"] == str(work / "chat")

def test_pair_missing_token_file_names_it(tmp_path):
    work = tmp_path / "work"; work.mkdir()
    (work / ".bot-token-orch").write_text("t\n", encoding="utf-8")
    r = _pair(tmp_path, work)
    assert r.returncode != 0 and ".bot-token-claude" in r.stderr

def _overlay(tmp_path, work):
    return run(tmp_path, "install", "--work-dir", str(work), "--phase", "overlay")

def test_overlay_copies_manifest_files(tmp_path):
    fetched(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    r = _overlay(tmp_path, work)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (work / "scripts/bot-up.sh").read_text(encoding="utf-8") == STUB
    assert os.access(work / "scripts/bot-up.sh", os.X_OK)
    assert (work / ".env.example").exists()
    assert (work / "chat/CLAUDE.md").exists()               # seed
    st = json.loads((tmp_path / ".config/discord-harness/state.json").read_text(encoding="utf-8"))
    assert "scripts/bot-up.sh" in st["overlay"]
    assert len(st["overlay"]["scripts/bot-up.sh"]) == 64    # sha256 기록

def test_overlay_claude_block_and_mcp_merge_nondestructive(tmp_path):
    fetched(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    original = "# 내 규칙\n\n소중한 내용.\n"
    (work / "CLAUDE.md").write_text(original, encoding="utf-8")
    (work / ".mcp.json").write_text(json.dumps({"mcpServers": {"mine": {"command": "x"}}}), encoding="utf-8")
    (work / "SESSION.md").write_text("세션 기록\n", encoding="utf-8")
    r = _overlay(tmp_path, work)
    assert r.returncode == 0, r.stdout + r.stderr
    text = (work / "CLAUDE.md").read_text(encoding="utf-8")
    assert original in text and "<!-- discord-multiagent:start -->" in text
    mcp = json.loads((work / ".mcp.json").read_text(encoding="utf-8"))
    assert "mine" in mcp["mcpServers"] and "codex" in mcp["mcpServers"]
    assert (work / "SESSION.md").read_text(encoding="utf-8") == "세션 기록\n"   # SESSION.md 무접촉
    st = json.loads((tmp_path / ".config/discord-harness/state.json").read_text(encoding="utf-8"))
    assert st["mcp_added"] == ["codex"]
    r2 = _overlay(tmp_path, work)                               # 멱등
    assert r2.returncode == 0
    assert (work / "CLAUDE.md").read_text(encoding="utf-8") == text

def test_overlay_seed_preserves_user_edit(tmp_path):
    fetched(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    _overlay(tmp_path, work)
    (work / "chat/CLAUDE.md").write_text("사용자 수정본\n", encoding="utf-8")
    _overlay(tmp_path, work)
    assert (work / "chat/CLAUDE.md").read_text(encoding="utf-8") == "사용자 수정본\n"

def test_overlay_append_lines_merges_gitignore_and_reverts_on_remove(tmp_path):
    fetched(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    original = "node_modules/\n"
    (work / ".gitignore").write_text(original, encoding="utf-8")
    r = _overlay(tmp_path, work)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "오버레이(줄 추가): " in r.stdout and ".gitignore += 5줄" in r.stdout
    text = (work / ".gitignore").read_text(encoding="utf-8")
    assert text.startswith(original)
    for line in ("# discord 하네스 비밀 — 커밋 금지 (harness-installer overlay)",
                 ".env", ".discord-state/", ".bot-token-*", ".webhook-url"):
        assert line in text.splitlines()
    st = json.loads((tmp_path / ".config/discord-harness/state.json").read_text(encoding="utf-8"))
    assert st["lines_added"][".gitignore"] == [
        "# discord 하네스 비밀 — 커밋 금지 (harness-installer overlay)",
        ".env", ".discord-state/", ".bot-token-*", ".webhook-url"]
    r2 = _overlay(tmp_path, work)                               # 멱등
    assert r2.returncode == 0
    assert (work / ".gitignore").read_text(encoding="utf-8") == text
    assert "오버레이(줄 추가): " not in r2.stdout
    r3 = run(tmp_path, "remove", "--work-dir", str(work))
    assert r3.returncode == 0, r3.stdout + r3.stderr
    assert (work / ".gitignore").read_text(encoding="utf-8") == original

def test_overlay_writes_bot_settings_with_merge(tmp_path):
    # 무인 봇 전제: discord reply·MCP 서버 사전 승인이 오케·수다 양쪽에 기록된다
    fetched(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    user_settings = {"permissions": {"allow": ["Bash(ls:*)"]}}
    (work / ".claude").mkdir()
    (work / ".claude/settings.local.json").write_text(json.dumps(user_settings), encoding="utf-8")
    r = _overlay(tmp_path, work)
    assert r.returncode == 0, r.stdout + r.stderr
    for rel in (".claude/settings.local.json", "chat/.claude/settings.local.json"):
        cfg = json.loads((work / rel).read_text(encoding="utf-8"))
        assert cfg["enableAllProjectMcpServers"] is True
        assert "mcp__plugin_discord_discord" in cfg["permissions"]["allow"]
        assert "mcp__plugin_discord_discord__reply" in cfg["permissions"]["allow"]
        # 대시보드 클로드 카드 데이터원 — statusLine 스냅샷 기록자 주입 (2026-08-05 실측:
        # 미주입 시 카드가 [Claude]·— 로 영구 공백)
        assert cfg["statusLine"]["type"] == "command"
        assert cfg["statusLine"]["command"].endswith(
            "usage-coach/scripts/statusline-command.sh")
        # 무인 권한 모드는 bot-up.sh 세션 플래그가 담당(프로젝트 defaultMode는
        # 무효 실측, 0.1.8 철회) — 설정 파일엔 주입하지 않는다
        assert "defaultMode" not in cfg["permissions"]
    # 기존 사용자 항목 보존(병합)
    orch = json.loads((work / ".claude/settings.local.json").read_text(encoding="utf-8"))
    assert "Bash(ls:*)" in orch["permissions"]["allow"]
    st = json.loads((tmp_path / ".config/discord-harness/state.json").read_text(encoding="utf-8"))
    assert st["settings_added"][".claude/settings.local.json"]["created"] is False
    assert st["settings_added"]["chat/.claude/settings.local.json"]["created"] is True

def test_remove_reverts_bot_settings(tmp_path):
    fetched(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    (work / ".claude").mkdir()
    (work / ".claude/settings.local.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}}), encoding="utf-8")
    assert _overlay(tmp_path, work).returncode == 0
    _token_files(work)
    assert _pair(tmp_path, work).returncode == 0
    r = run(tmp_path, "remove", "--work-dir", str(work))
    assert r.returncode == 0, r.stdout + r.stderr
    # 사용자 파일: 설치기 추가분만 회수, 사용자 항목 보존
    orch = json.loads((work / ".claude/settings.local.json").read_text(encoding="utf-8"))
    assert orch["permissions"]["allow"] == ["Bash(ls:*)"]
    assert "enableAllProjectMcpServers" not in orch
    assert "statusLine" not in orch                  # 설치기 주입분 회수
    assert "defaultMode" not in orch.get("permissions", {})
    # 설치기가 만든 파일: 통째 제거
    assert not (work / "chat/.claude/settings.local.json").exists()

def test_remove_keeps_state_on_warn_then_resumes(tmp_path):
    # 부분 실패 시 state 를 보존해야 2차 remove 가 이어서 제거할 수 있다
    base, work = _installed(tmp_path)
    (work / "scripts/post-as.sh").write_text("#!/bin/bash\n# 사용자 수정\n", encoding="utf-8")
    r = run(tmp_path, "remove", "--work-dir", str(work))
    assert r.returncode == 0
    assert "재실행하면 이어서" in r.stdout
    state = tmp_path / ".config/discord-harness/state.json"
    assert state.exists()
    r2 = run(tmp_path, "remove")           # state 가 work_dir 를 기억한다
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert (work / "scripts/post-as.sh").exists()   # 사용자 수정분은 계속 보존

def test_overlay_without_fetch_fails_with_hint(tmp_path):
    work = tmp_path / "work"; work.mkdir()
    r = _overlay(tmp_path, work)
    assert r.returncode != 0 and "fetch" in r.stderr

def _installed(tmp_path):
    """fetch → overlay → pair 까지 마친 작업 폴더를 준비한다."""
    base = fetched(tmp_path)
    work = tmp_path / "work"; work.mkdir()
    assert _overlay(tmp_path, work).returncode == 0
    _token_files(work)
    assert _pair(tmp_path, work).returncode == 0
    (tmp_path / "Library/LaunchAgents").mkdir(parents=True, exist_ok=True)
    return base, work

def _bot_sessions(work):
    """cmd_pair가 실제로 생성한 bots.json의 세션 이름 — Windows는 호스트 접미사가
    붙으므로(결정 9) "orchestrator"/"chat-claude" 리터럴을 시임 키로 쓰면 안 된다."""
    data = json.loads((work / "bots.json").read_text(encoding="utf-8"))
    m = {}
    for bot in data["bots"]:
        if bot["name"] == "orchestrator":
            m["orch"] = bot["session"]
        elif bot["name"] == "chat-claude":
            m["chat"] = bot["session"]
    return m

def test_delegate_dry_run_prints_commands_only(tmp_path):
    base, work = _installed(tmp_path)
    r = run(tmp_path, "install", "--work-dir", str(work), "--phase", "delegate",
            "--dashboard", "--autostart", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    if sys.platform == "win32":
        # 브리지는 Windows 배선 미완료라 SKIP — 설치 시도 자체를 안 한다.
        # 대시보드·자동 기동은 각각 dash_win.py install / bot_win.py autostart-install에
        # 위임(dry-run이라 실제 실행 없이 명령 문자열만 출력).
        assert "[SKIP] 브리지" in r.stdout and "Phase 2 진행 중" in r.stdout
        assert "install.sh" not in r.stdout
        assert "install-autostart.sh" not in r.stdout
        assert "위임(dry-run):" in r.stdout
        assert "dash_win.py" in r.stdout and "install" in r.stdout
        assert "bot_win.py" in r.stdout and "autostart-install" in r.stdout
    else:
        repos = tmp_path / ".local/share/discord-harness/repos"
        assert f"위임(dry-run): (cd {repos / 'codex-discord'})" in r.stdout
        assert os.sep.join(("codex-discord", "scripts", "install.sh")) in r.stdout
        assert os.sep.join(("usage-coach", "scripts", "install.sh")) in r.stdout
        assert os.sep.join(("scripts", "install-autostart.sh")) in r.stdout
    assert not (tmp_path / "Library/LaunchAgents/com.discord-harness.chat-claude.plist").exists()

def test_delegate_dashboard_skip_if_dash_win_missing(tmp_path):
    if sys.platform != "win32":
        pytest.skip("dash_win.py 부재 SKIP은 Windows 전용 경로")
    base, work = _installed(tmp_path)
    dash_script = tmp_path / ".local/share/discord-harness/repos/usage-coach/scripts/dash_win.py"
    dash_script.unlink()
    r = run(tmp_path, "install", "--work-dir", str(work), "--phase", "delegate",
            "--dashboard", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[SKIP] 대시보드" in r.stdout and "dash_win.py" in r.stdout and "없음" in r.stdout

def test_delegate_assembles_bridge_envs(tmp_path):
    if sys.platform == "win32":
        pytest.skip("브리지(codex-discord) 설치는 Windows에서 SKIP — 2차 범위(이 수직 슬라이스 밖)")
    base, work = _installed(tmp_path)
    r = run(tmp_path, "install", "--work-dir", str(work), "--phase", "delegate", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    bridge = tmp_path / ".local/share/discord-harness/repos/codex-discord"
    env = (bridge / ".env").read_text(encoding="utf-8")
    assert "DISCORD_TOKEN=tok-codex" in env and "ALLOWED_USER_IDS=999" in env
    # 작업 폴더는 봇별 분리 — 정본 실측(codex/gemini-discord-workspace). 공유 폴더는
    # 동시 파일 작업 충돌 위험 + "chat/=수다 클로드 전용" 결정 위반 (2026-08-05 정정)
    assert f"CODEX_WORKDIR={work / 'codex-discord-workspace'}" in env and "CHANNEL_IDS=222" in env
    assert "TRIGGER_NAME=코덱스" in env
    # 코덱스는 프로덕션 실측과 동일하게 TUI 모드 — tmux 세션이 보여야 한다
    assert "TUI_PANE=codex-live:0.0" in env and "TUI_CHANNEL_ID=222" in env
    gem = (bridge / ".env.gemini").read_text(encoding="utf-8")
    assert "DISCORD_TOKEN=tok-gemini" in gem and "ENGINE=agy" in gem
    assert f"CODEX_WORKDIR={work / 'gemini-discord-workspace'}" in gem
    assert "DATA_DIR=data-gemini" in gem and "TRIGGER_NAME=제미나이" in gem
    assert (work / "codex-discord-workspace").is_dir()
    assert (work / "gemini-discord-workspace").is_dir()
    if sys.platform != "win32":
        assert oct((bridge / ".env").stat().st_mode)[-3:] == "600"
    # 멱등 — 재실행해도 기존 .env 보존
    (bridge / ".env").write_text("DISCORD_TOKEN=user-edited\n", encoding="utf-8")
    run(tmp_path, "install", "--work-dir", str(work), "--phase", "delegate", "--dry-run")
    assert (bridge / ".env").read_text(encoding="utf-8") == "DISCORD_TOKEN=user-edited\n"

def test_delegate_real_run_writes_chat_plist(tmp_path):
    if sys.platform == "win32":
        pytest.skip("Windows autostart는 bots.json+schtasks 경로(ADR-0002/0003) — "
                    "bot_win.py autostart-install 구현 후 별도 테스트로 대체 예정, 미구현")
    base, work = _installed(tmp_path)
    r = run(tmp_path, "install", "--work-dir", str(work), "--phase", "delegate", "--autostart")
    assert r.returncode == 0, r.stdout + r.stderr   # fixture 위임 스크립트 = echo stub
    p = tmp_path / "Library/LaunchAgents/com.discord-harness.chat-claude.plist"
    args = plistlib.loads(p.read_bytes())["ProgramArguments"]
    assert args[args.index("-s") + 1] == "chat-claude" and "new-session" in args
    cmd = args[-1]
    assert f"cd {work}/chat" in cmd
    assert f"DISCORD_STATE_DIR={work}/chat/.discord-state" in cmd
    assert "scripts/bot-up.sh" in cmd and "--channels plugin:discord@claude-plugins-official" in cmd

PLUG_CWD = "/tmp/x/.claude/plugins/cache/claude-plugins-official/discord/0.0.4"

def _seams(panes, procs):
    """프로세스 실존 판정 시임 — HARNESS_FAKE_PANES(세션→pane pid) + HARNESS_FAKE_PS(ps 스냅샷)"""
    return {"HARNESS_FAKE_PANES": json.dumps(panes),
            "HARNESS_FAKE_PS": "\n".join(f"{p} {pp} {c}" for p, pp, c in procs)}

def _live_bots_seams():
    """봇 2종 tmux 세션 + claude + discord MCP 서버 + codex TUI가 전부 살아 있는 정상 상태"""
    return _seams(
        {"orchestrator": 100, "chat-claude": 200, "codex-live": 300},
        [(100, 1, "/Users/x/.local/bin/claude --channels plugin:discord@claude-plugins-official"),
         (150, 100, f"bun run --cwd {PLUG_CWD} --shell=bun --silent start"),
         (200, 1, "claude --channels plugin:discord@claude-plugins-official"),
         (250, 200, f"bun run --cwd {PLUG_CWD} --shell=bun --silent start"),
         (300, 1, "zsh"),
         # npm 배포판 회귀: codex가 node 런처(#!/usr/bin/env node)로 떠도 가동 판정 (2026-08-05 실측)
         (310, 300, "node /Users/x/.local/bin/codex -s workspace-write -c sandbox_workspace_write.network_access=true")])

def _rollout(tmp_path, cwd):
    """codex 롤아웃 fixture — 브리지 세션 특정의 검출원 (session_meta.cwd 일치)"""
    d = tmp_path / ".codex/sessions/2026/08/05"
    d.mkdir(parents=True, exist_ok=True)
    (d / "rollout-2026-08-05T12-00-00-aaaaaaaa-1111-2222-3333-444444444444.jsonl").write_text(
        json.dumps({"type": "session_meta",
                    "payload": {"session_id": "aaaaaaaa-1111-2222-3333-444444444444",
                                "cwd": str(cwd)}}) + "\n", encoding="utf-8")

def _mcp_log_dir(tmp_path, workdir):
    if sys.platform == "win32":
        # S2 확정(docs/spikes) — Windows는 %LOCALAPPDATA%/claude-cli-nodejs/Cache/<맹글링>
        mangled = re.sub(r"[\\/:.]", "-", str(workdir))
        return tmp_path / "claude-cli-nodejs/Cache" / mangled / "mcp-logs-plugin-discord-discord"
    mangled = re.sub(r"[/.]", "-", str(workdir))
    return tmp_path / "Library/Caches/claude-cli-nodejs" / mangled / "mcp-logs-plugin-discord-discord"

def _mcp_log(tmp_path, workdir, line):
    d = _mcp_log_dir(tmp_path, workdir)
    d.mkdir(parents=True, exist_ok=True)
    (d / "2026-08-04.jsonl").write_text(json.dumps({"msg": line}) + "\n", encoding="utf-8")

def test_verify_ok_with_fixture_logs(tmp_path):
    if sys.platform == "win32":
        pytest.skip("브리지·코덱스 TUI·tmux 세션명 전제 macOS 전용 — Windows는 2차 범위 SKIP")
    base, work = _installed(tmp_path)
    bridge = tmp_path / ".local/share/discord-harness/repos/codex-discord"
    run(tmp_path, "install", "--work-dir", str(work), "--phase", "delegate", "--dry-run")
    _mcp_log(tmp_path, work, "Successfully connected to Discord")
    _mcp_log(tmp_path, work / "chat", "Successfully connected to Discord")
    _rollout(tmp_path, work / "codex-discord-workspace")
    (bridge / "logs").mkdir(exist_ok=True)
    (bridge / "logs/daemon.log").write_text("로그인: codex#1 / 엔진 codex\n", encoding="utf-8")
    (bridge / "logs/daemon-gemini.log").write_text("로그인: gem#1 / 엔진 agy\n", encoding="utf-8")
    (bridge / "data").mkdir(exist_ok=True)
    (bridge / "data/daemon.pid").write_text(str(os.getpid()), encoding="utf-8")
    r = run(tmp_path, "verify", "--work-dir", str(work), "--skip-webhook", "--wait", "5",
            env_extra=_live_bots_seams())
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[OK] 오케스트레이터" in r.stdout and "[OK] 수다 클로드" in r.stdout
    assert "[OK] 코덱스" in r.stdout and "[OK] 제미나이" in r.stdout
    assert "[OK] tmux 세션 orchestrator claude 가동" in r.stdout
    assert "[OK] 코덱스 TUI(codex-live:0.0) codex 가동" in r.stdout

def test_verify_webhook_probe_sends_user_agent(tmp_path):
    # UA 없는 프로브는 Cloudflare(1010)에 차단돼 오탐 FAIL 을 낸다 — 실측 회귀
    base, work = _installed(tmp_path)
    _mcp_log(tmp_path, work, "Successfully connected to Discord")
    _mcp_log(tmp_path, work / "chat", "Successfully connected to Discord")
    bridge = tmp_path / ".local/share/discord-harness/repos/codex-discord"
    (bridge / "logs").mkdir(exist_ok=True)
    (bridge / "logs/daemon.log").write_text("로그인: codex#1 / 엔진 codex\n", encoding="utf-8")
    (bridge / "data").mkdir(exist_ok=True)
    (bridge / "data/daemon.pid").write_text(str(os.getpid()), encoding="utf-8")
    seen = {}
    class Probe(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["ua"] = self.headers.get("User-Agent")
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(204); self.end_headers()
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), Probe)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = tmp_path / ".config/usage-coach"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "discord.json").write_text(json.dumps(
        {"webhook_url": f"http://127.0.0.1:{srv.server_port}/hook"}), encoding="utf-8")
    try:
        r = run(tmp_path, "verify", "--work-dir", str(work), env_extra=_live_bots_seams())
    finally:
        srv.shutdown()
    assert "[OK] 웹훅 시험 발사 성공" in r.stdout, r.stdout + r.stderr
    assert seen["ua"] == "usage-coach-dash"

def test_verify_connection_failed_is_fail(tmp_path):
    base, work = _installed(tmp_path)
    _mcp_log(tmp_path, work, "Connection failed: invalid token")
    r = run(tmp_path, "verify", "--work-dir", str(work), "--skip-webhook")
    assert r.returncode == 1
    assert "[FAIL] 오케스트레이터" in r.stdout

def test_verify_fails_on_stale_mcp_log(tmp_path):
    # MCP가 아예 안 뜨면 로그 파일이 안 생긴다 — 이전 기동의 '성공' 로그가
    # 합격으로 오판되면 안 된다 (2026-08-05 실측)
    base, work = _installed(tmp_path)
    _mcp_log(tmp_path, work, "Successfully connected to Discord")
    log_dir = _mcp_log_dir(tmp_path, work)
    old = next(log_dir.glob("*.jsonl"))
    os.utime(old, (1000000, 1000000))            # 설치 이전으로 되돌림
    r = run(tmp_path, "verify", "--work-dir", str(work), "--skip-webhook")
    assert r.returncode == 1
    assert "[FAIL] 오케스트레이터" in r.stdout and "미기동" in r.stdout
    assert "bot-restart.sh" in r.stdout

def test_verify_fresh_log_without_server_process_is_fail(tmp_path):
    # 2026-08-05 3차 실측: 진단용 `claude mcp list`가 남긴 신선한 성공 로그만으로
    # 합격 처리되면 안 된다 — 봇 세션 자손에 MCP 서버 프로세스가 실존해야 OK
    base, work = _installed(tmp_path)
    sessions = _bot_sessions(work)
    _mcp_log(tmp_path, work, "Successfully connected to Discord")
    _mcp_log(tmp_path, work / "chat", "Successfully connected to Discord")
    env = _seams({sessions["orch"]: 100, sessions["chat"]: 200},
                 [(100, 1, "claude --channels plugin:discord@claude-plugins-official"),
                  (200, 1, "claude --channels plugin:discord@claude-plugins-official")])
    r = run(tmp_path, "verify", "--work-dir", str(work), "--skip-webhook", env_extra=env)
    assert r.returncode == 1
    assert "[FAIL] 오케스트레이터" in r.stdout and "프로세스 없음" in r.stdout

def test_verify_tmux_session_without_claude_is_warn(tmp_path):
    # 락 대기 중 빈 세션이 '생존' OK로 찍히면 오해를 부른다 (3차 실측 #5)
    base, work = _installed(tmp_path)
    sessions = _bot_sessions(work)
    env = _seams({sessions["orch"]: 100, sessions["chat"]: 200},
                 [(100, 1, "bash scripts/bot-up.sh --channels plugin:discord@claude-plugins-official"),
                  (200, 1, "bash scripts/bot-up.sh --channels plugin:discord@claude-plugins-official")])
    r = run(tmp_path, "verify", "--work-dir", str(work), "--skip-webhook", env_extra=env)
    assert f"[WARN] 세션 {sessions['orch']}: 세션은 있으나 claude 프로세스 없음" in r.stdout

def test_verify_codex_tui_pane_without_codex_is_fail(tmp_path):
    if sys.platform == "win32":
        pytest.skip("코덱스 TUI는 Windows에서 SKIP — codex-discord 2차 범위")
    # 3차 실측: codex-live 세션은 있는데 pane이 zsh(codex 죽음)이면 브리지가 호명을
    # 거부한다 — verify가 이를 못 보면 11/11 OK 오탐. 복구 경로(tui-up.sh) 안내 필수
    base, work = _installed(tmp_path)
    run(tmp_path, "install", "--work-dir", str(work), "--phase", "delegate", "--dry-run")
    _mcp_log(tmp_path, work, "Successfully connected to Discord")
    _mcp_log(tmp_path, work / "chat", "Successfully connected to Discord")
    env = _seams({"orchestrator": 100, "chat-claude": 200, "codex-live": 300},
                 [(100, 1, "claude --channels plugin:discord@claude-plugins-official"),
                  (150, 100, f"bun run --cwd {PLUG_CWD} --shell=bun --silent start"),
                  (200, 1, "claude --channels plugin:discord@claude-plugins-official"),
                  (250, 200, f"bun run --cwd {PLUG_CWD} --shell=bun --silent start"),
                  (300, 1, "zsh")])          # codex 없음 — pane에 셸만 남음
    r = run(tmp_path, "verify", "--work-dir", str(work), "--skip-webhook", env_extra=env)
    assert r.returncode == 1
    assert "[FAIL] 코덱스 TUI" in r.stdout and "tui-up.sh" in r.stdout

def test_verify_codex_tui_without_rollout_is_fail(tmp_path):
    if sys.platform == "win32":
        pytest.skip("코덱스 TUI는 Windows에서 SKIP — codex-discord 2차 범위")
    # 3차 실측(회신6): codex v0.146.0은 세션 UUID를 화면에 안 보여 브리지가
    # 롤아웃 session_meta(cwd)로 세션을 특정한다 — cwd 일치 롤아웃이 없으면
    # TUI가 살아 있어도 호명이 실패하므로 verify가 FAIL로 잡아야 한다
    base, work = _installed(tmp_path)
    run(tmp_path, "install", "--work-dir", str(work), "--phase", "delegate", "--dry-run")
    _mcp_log(tmp_path, work, "Successfully connected to Discord")
    _mcp_log(tmp_path, work / "chat", "Successfully connected to Discord")
    r = run(tmp_path, "verify", "--work-dir", str(work), "--skip-webhook",
            env_extra=_live_bots_seams())        # 롤아웃 fixture 없음
    assert r.returncode == 1
    assert "[FAIL] 코덱스 TUI" in r.stdout and "롤아웃" in r.stdout

def test_verify_wait_polls_until_timeout(tmp_path):
    # bot-up 직렬화(락 대기 최대 300초+연결 240초) 중 조기 FAIL 방지 — 상한까지 폴링 후 판정
    base, work = _installed(tmp_path)          # MCP 로그 없음 → 끝내 FAIL
    t0 = time.time()
    r = run(tmp_path, "verify", "--work-dir", str(work), "--skip-webhook", "--wait", "2",
            env_extra=_seams({}, []))
    assert r.returncode == 1
    assert time.time() - t0 >= 2

def test_doctor_warns_on_pin_mismatch(tmp_path):
    fetched(tmp_path)
    sp = tmp_path / ".config/discord-harness/state.json"
    st = json.loads(sp.read_text(encoding="utf-8"))
    st["repos"]["usage-coach"]["ref"] = "v9.9.9"
    sp.write_text(json.dumps(st), encoding="utf-8")
    r = run(tmp_path, "doctor")
    assert "[WARN]" in r.stdout and "usage-coach" in r.stdout and "v9.9.9" in r.stdout

def test_doctor_warns_on_missing_contract_file(tmp_path):
    fetched(tmp_path)
    (tmp_path / ".local/share/discord-harness/repos/usage-coach/scripts/uninstall.sh").unlink()
    r = run(tmp_path, "doctor")
    assert "[WARN]" in r.stdout and "uninstall.sh" in r.stdout

def test_doctor_fails_on_manifest_schema_mismatch(tmp_path):
    fetched(tmp_path)
    mp = tmp_path / ".local/share/discord-harness/repos/discord-multiagent/install/overlay-manifest.json"
    mf = json.loads(mp.read_text(encoding="utf-8")); mf["schema_version"] = 99
    mp.write_text(json.dumps(mf), encoding="utf-8")
    r = run(tmp_path, "doctor")
    assert r.returncode == 1 and "schema_version" in r.stdout

def test_doctor_plugin_version_check(tmp_path):
    fetched(tmp_path)
    old = tmp_path / ".claude/plugins/cache/folder-bot/folder-bot/0.0.1"
    old.mkdir(parents=True)
    r = run(tmp_path, "doctor")
    assert "folder-bot" in r.stdout and "[WARN]" in r.stdout

def test_remove_diff_zero_and_preserves_user_data(tmp_path):
    fetched(tmp_path)
    (tmp_path / "Library/LaunchAgents").mkdir(parents=True, exist_ok=True)
    work2 = tmp_path / "work2"; work2.mkdir()
    orig_md = "# 내 규칙\n\n소중한 내용.\n"
    orig_mcp = json.dumps({"mcpServers": {"mine": {"command": "x"}}}, indent=2) + "\n"
    (work2 / "CLAUDE.md").write_text(orig_md, encoding="utf-8")
    (work2 / ".mcp.json").write_text(orig_mcp, encoding="utf-8")
    (work2 / "SESSION.md").write_text("세션\n", encoding="utf-8")
    assert _overlay(tmp_path, work2).returncode == 0
    _token_files(work2)
    assert _pair(tmp_path, work2).returncode == 0
    r = run(tmp_path, "install", "--work-dir", str(work2), "--phase", "delegate", "--autostart")
    assert r.returncode == 0, r.stdout + r.stderr
    r = run(tmp_path, "remove", "--work-dir", str(work2))
    assert r.returncode == 0, r.stdout + r.stderr
    # diff 0: 설치 전 존재하던 파일은 원문 동일
    assert (work2 / "CLAUDE.md").read_text(encoding="utf-8") == orig_md
    mcp = json.loads((work2 / ".mcp.json").read_text(encoding="utf-8"))
    assert "mine" in mcp["mcpServers"] and "codex" not in mcp["mcpServers"]
    assert (work2 / "SESSION.md").read_text(encoding="utf-8") == "세션\n"
    # 설치기가 만든 것은 제거
    assert not (work2 / "scripts/bot-up.sh").exists()
    assert not (work2 / ".env.example").exists()
    assert not (work2 / ".gitignore").exists()
    assert not (tmp_path / "Library/LaunchAgents/com.discord-harness.chat-claude.plist").exists()
    assert not (tmp_path / ".local/share/discord-harness/repos").exists()
    assert not (tmp_path / ".config/discord-harness/state.json").exists()
    # 사용자 데이터·비밀 보존
    assert (work2 / ".env").exists()
    assert (work2 / ".discord-state/.env").exists()
    assert (work2 / "chat/.discord-state/.env").exists()

def test_remove_warns_on_delegated_uninstall_failure(tmp_path):
    base, work = _installed(tmp_path)
    coach_uninstall = tmp_path / ".local/share/discord-harness/repos/usage-coach/scripts/uninstall.sh"
    coach_uninstall.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
    coach_uninstall.chmod(0o755)
    r = run(tmp_path, "remove", "--work-dir", str(work))
    assert r.returncode == 0, r.stdout + r.stderr   # 계속 진행 의미론 유지
    assert "[WARN] 제거 스크립트 실패" in r.stdout

def test_remove_preserves_user_modified_overlay(tmp_path):
    base, work = _installed(tmp_path)
    (work / "scripts/post-as.sh").write_text("#!/bin/bash\n# 사용자 수정\n", encoding="utf-8")
    r = run(tmp_path, "remove", "--work-dir", str(work))
    assert r.returncode == 0
    assert (work / "scripts/post-as.sh").exists()
    assert "[WARN]" in r.stdout and "post-as.sh" in r.stdout

def test_engine_source_never_mentions_bootout():
    assert "bootout" not in HARNESSCTL.read_text(encoding="utf-8")
