"""Regression tests for the 2026-10-31 bug hunt and review (tracking 009-011, 029-050).

Each one failed before its fix.
"""

import os
import threading
import time

import pytest
import yaml
from textual.widgets import DataTable

from ccdeck import config, hook, installer, notify, remote, sessions
from ccdeck.config import Notify
from ccdeck.sessions import Status
from ccdeck.tui import CCDeck

from .conftest import needs_tmux, wait_for


def _cat_session(env, name="x"):
    """A config with session `name` plus a running tmux `cc-<name>` that just echoes input."""
    env.write_config(f"sessions: [{{name: {name}, dir: /tmp}}]\n")
    cfg = config.load()
    r = env.tmux("new-session", "-d", "-s", f"cc-{name}", "-x", "120", "-y", "20", "cat")
    assert r.returncode == 0, r.stderr
    return cfg


def _running(cfg, state="idle"):
    return [Status(s, cfg.host_of(s), cfg.account_of(s), state=state) for s in cfg.sessions]


# ------------------------------------------------------------------ 029 semicolons


@needs_tmux
def test_029_typed_semicolons_reach_the_session(env):
    cfg = _cat_session(env)
    sessions.send_input(cfg, "x", [("text", "ls;")])  # a batch ending in ';'
    sessions.send_input(cfg, "x", [("text", ";")])    # one key per batch (fast host)
    sessions.send_input(cfg, "x", [("text", "a\\;")])  # backslash + semicolon
    sessions.send_input(cfg, "x", [("key", "Enter")])
    wait_for(lambda: "ls" in env.pane("x"), what="typed text")
    time.sleep(0.3)
    assert "ls;;a\\;" in env.pane("x")


@needs_tmux
def test_029_pasted_semicolon_reaches_the_session(env):
    cfg = _cat_session(env)
    sessions.paste(cfg, "x", "echo hi;")
    sessions.send_input(cfg, "x", [("key", "Enter")])
    wait_for(lambda: "echo hi" in env.pane("x"), what="pasted text")
    time.sleep(0.3)
    assert "echo hi;" in env.pane("x")


# ------------------------------------------------------------------ 030 live typing race


async def test_030_keys_typed_after_switching_live_session_go_to_the_new_one(env, monkeypatch):
    sent = []
    release = threading.Event()

    def slow_send(cfg, name, chunks):
        if not sent:
            release.wait(5)  # first batch is slow (SSH round trip)
        sent.append((name, list(chunks)))

    monkeypatch.setattr(sessions, "send_input", slow_send)
    monkeypatch.setattr(sessions, "screen", lambda cfg, name: sessions.Screen(f"screen {name}"))
    monkeypatch.setattr(sessions, "fit", lambda *a: None)
    env.write_config("sessions: [{name: a, dir: /x}, {name: b, dir: /y}]\n")
    cfg = config.load()
    app = CCDeck(cfg, poll_on_mount=False)
    async with app.run_test(size=(150, 40)) as pilot:
        app.apply_poll(_running(cfg), {})
        table = app.query_one(DataTable)
        table.move_cursor(row=0)
        await pilot.pause()
        assert app.selected_name() == "a"
        await pilot.press("enter", "1")       # live into a; the send of "1" is in flight
        await pilot.press("ctrl+q")       # stop typing into a
        table.focus()
        table.move_cursor(row=1)
        await pilot.pause()
        assert app.selected_name() == "b"
        await pilot.press("enter", "2")       # live into b
        assert app.live == "b"
        release.set()
        await app.workers.wait_for_complete()
        assert ("b", [("text", "2")]) in sent, sent


# ------------------------------------------------------------------ 031 paste reordering


async def test_031_paste_keeps_its_place_among_typed_text(env, monkeypatch):
    order = []
    monkeypatch.setattr(sessions, "send_input",
                        lambda cfg, name, chunks: order.extend(chunks))
    env.write_config("sessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    app = CCDeck(cfg, poll_on_mount=False)
    async with app.run_test(size=(150, 40)):
        with app._input_lock:
            app._input = [("a", "text", "see "), ("a", "paste", "/tmp/log.txt"),
                          ("a", "text", " please")]
            app._sending = True
        app.input_sender()
        await app.workers.wait_for_complete()
    assert order == [("text", "see "), ("paste", "/tmp/log.txt"), ("text", " please")], order


# ------------------------------------------------------------------ 033 settings.json symlink


def test_033_setup_keeps_symlinked_settings(env):
    dotfiles = env.home / "dotfiles"
    dotfiles.mkdir()
    real = dotfiles / "claude-settings.json"
    real.write_text('{"model": "opus"}\n')
    os.chmod(real, 0o644)
    cdir = env.home / ".claude"
    cdir.mkdir()
    (cdir / "settings.json").symlink_to(real)
    proc = remote.python(config.Host("local"), installer.MERGE_SCRIPT, "~/.claude", "install",
                         ",".join(installer.EVENTS), ",".join(installer.EVENTS))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (cdir / "settings.json").is_symlink(), "symlink replaced by a regular file"
    assert "hook.py" in real.read_text()
    assert (real.stat().st_mode & 0o777) == 0o644


# ------------------------------------------------------------------ 034 ctrl+p while live


async def test_034_ctrl_p_reaches_the_session_while_typing_live(env, monkeypatch):
    sent = []
    monkeypatch.setattr(sessions, "send_input", lambda cfg, name, chunks: sent.extend(chunks))
    monkeypatch.setattr(sessions, "screen", lambda cfg, name: sessions.Screen("screen"))
    monkeypatch.setattr(sessions, "fit", lambda *a: None)
    env.write_config("sessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    app = CCDeck(cfg, poll_on_mount=False)
    async with app.run_test(size=(150, 40)) as pilot:
        app.apply_poll(_running(cfg), {})
        await pilot.pause()
        await pilot.press("enter", "ctrl+p")
        await pilot.pause()
        await app.workers.wait_for_complete()
        assert app.live == "a" and len(app.screen_stack) == 1
        assert ("key", "C-p") in sent, sent


# ------------------------------------------------------------------ 035 missed repeat alerts


def _st(cfg, state, ts, message="", alerts=0):
    s = cfg.sessions[0]
    return Status(s, cfg.host_of(s), cfg.account_of(s), state=state, ts=ts, message=message,
                  alerts=alerts)


def test_035_new_prompt_between_polls_still_alerts(monkeypatch):
    monkeypatch.setattr(notify, "send", lambda *a: None)
    cfg = config.parse(yaml.safe_load("sessions: [{name: a, dir: /x}]"))
    n = notify.Notifier(Notify())
    n.update([_st(cfg, "waiting", 100, "wants to use Bash: ls", alerts=1)])  # baseline
    # you approved; Claude ran ls and asked again before the next poll
    sent = n.update([_st(cfg, "waiting", 105, "wants to use Bash: rm -rf build", alerts=2)])
    assert sent == [("a needs you", "wants to use Bash: rm -rf build")]
    # a later hook event that isn't a new prompt (newer ts, same count): no duplicate (007)
    assert n.update([_st(cfg, "waiting", 107, "wants to use Bash: rm -rf build", alerts=2)]) == []
    # a quick second reply: done -> done
    n.update([_st(cfg, "done", 110, "first", alerts=3)])
    assert n.update([_st(cfg, "done", 120, "second", alerts=4)]) == [("a finished", "second")]
    # older hooks without the counter behave as before
    assert n.update([_st(cfg, "done", 130, "third")]) == []


def test_035_hook_counts_each_alert_once():
    s = {}
    for event, payload in [
        ("UserPromptSubmit", {"prompt": "go"}),
        ("PermissionRequest", {"tool_name": "Bash", "tool_input": {"command": "ls"}}),
        ("Notification", {"message": "Claude needs your permission to use Bash",
                          "notification_type": "permission_prompt"}),  # same prompt
        ("PostToolUse", {"tool_name": "Bash"}),
        ("Stop", {"last_assistant_message": "done"}),
        ("Notification", {"message": "Claude is waiting for your input",
                          "notification_type": "idle_prompt"}),  # nudge, not new
    ]:
        s = hook.apply(s, event, payload)
    assert s["alerts"] == 2 and s["state"] == "done"


# ------------------------------------------------------------------ 036 compaction


def test_036_compaction_mid_turn_keeps_busy():
    state = {"state": "busy", "message": "using Bash", "session_id": "s1"}
    new = hook.apply(dict(state), "SessionStart", {"session_id": "s1", "source": "compact"})
    assert new["state"] == "busy"
    # a fresh start or /clear is still idle
    for source in ("startup", "clear"):
        assert hook.apply(dict(state), "SessionStart", {"source": source})["state"] == "idle"


# ------------------------------------------------------------------ 037 auth_success


def test_037_informational_notification_is_not_needs_you():
    new = hook.apply({"state": "idle"}, "Notification",
                     {"notification_type": "auth_success", "message": "Authentication successful"})
    assert new["state"] != "waiting"
    for kind in ("agent_completed", "elicitation_complete", "plugin_notification"):
        assert hook.apply({"state": "busy"}, "Notification",
                          {"notification_type": kind, "message": "x"})["state"] == "busy"
    for kind in ("permission_prompt", "elicitation_dialog", "agent_needs_input", None):
        new = hook.apply({"state": "busy"}, "Notification",
                         {"notification_type": kind, "message": "Claude needs you"})
        assert new["state"] == "waiting" and new["alerts"] == 1


# ------------------------------------------------------------------ 038 refresh: .inf


def test_038_infinite_refresh_is_rejected_or_saves(env):
    for bad in (".inf", ".nan", "-1", "99999"):
        env.write_config(f"refresh: {bad}\nsessions: [{{name: a, dir: /x}}]\n")
        with pytest.raises(config.ConfigError, match="refresh"):
            config.load()
    env.write_config("refresh: 0.5\nsessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    assert cfg.refresh == 1.0
    config.save(cfg)


# ------------------------------------------------------------------ 040 approved, still "needs you"


def test_040_answering_from_ccdeck_clears_needs_you(env):
    """No hook fires on approval: ccdeck flips waiting -> busy itself, but only if the state
    is still the prompt it saw (a newer prompt is never overwritten)."""
    import json
    env.write_config("sessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    path = env.home / ".ccdeck" / "state" / "a.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"state": "waiting", "message": "wants to use Bash: make",
                                "ts": 100.25}))
    sessions.mark_answered(cfg, "a", 99.0)  # stale: a newer prompt arrived since
    assert json.loads(path.read_text())["state"] == "waiting"
    sessions.mark_answered(cfg, "a", 100.25)
    assert json.loads(path.read_text())["state"] == "busy"
    path.unlink()
    sessions.mark_answered(cfg, "a", 100.25)  # no state file: quietly nothing
    assert not path.exists()


def test_040_reconcile_sees_a_decline_after_answering(tmp_path):
    t = tmp_path / "t.jsonl"
    t.write_text('{"type": "user", "message": {"content": [{"type": "tool_result", '
                 '"is_error": true, "content": "The user doesn\'t want to proceed with this '
                 'tool use."}]}}\n')
    state = {"state": "busy", "message": "answered, working…", "ts": 1.0,
             "transcript_path": str(t)}
    assert hook.reconcile(state)["state"] == "idle"


async def test_040_digit_and_live_enter_mark_the_prompt_answered(env, monkeypatch):
    marked, sent = [], []
    monkeypatch.setattr(sessions, "mark_answered", lambda cfg, name, ts: marked.append((name, ts)))
    monkeypatch.setattr(sessions, "send_key", lambda cfg, name, key: sent.append(key))
    monkeypatch.setattr(sessions, "send_input", lambda cfg, name, chunks: sent.extend(chunks))
    monkeypatch.setattr(sessions, "screen", lambda cfg, name: sessions.Screen("screen"))
    monkeypatch.setattr(sessions, "fit", lambda *a: None)
    env.write_config("sessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    app = CCDeck(cfg, poll_on_mount=False)
    app.action_refresh = lambda: None  # keep the statuses below (no real polling)
    async with app.run_test(size=(150, 40)) as pilot:
        app.apply_poll([_st(cfg, "waiting", 42.5)], {})
        await pilot.pause()
        await pilot.press("1")
        await app.workers.wait_for_complete()
        assert marked == [("a", 42.5)]
        await pilot.press("enter", *"ok", "enter")  # typing text doesn't answer; Enter does
        await app.workers.wait_for_complete()
        assert marked == [("a", 42.5), ("a", 42.5)]
        assert ("answered", 42.5) not in sent and ("key", "Enter") in sent
        app.apply_poll([_st(cfg, "busy", 43.0)], {})
        await pilot.press("enter")  # not waiting any more: nothing to mark
        await app.workers.wait_for_complete()
        assert len(marked) == 2


# ------------------------------------------------------------------ 009 hooks missing per account


def test_009_hand_edited_account_folder_gets_hooks():
    from ccdeck.forms import new_pairs
    old = config.parse(yaml.safe_load(
        "accounts: {work: {config_dir: ~/.claude-work}}\n"
        "sessions: [{name: a, dir: /x, account: work}]"))
    moved = config.parse(yaml.safe_load(
        "accounts: {work: {config_dir: ~/.claude-work2}}\n"
        "sessions: [{name: a, dir: /x, account: work}]"))
    assert new_pairs(old, moved) == ["local"]  # same account, new folder: needs hooks
    assert new_pairs(old, old) == []


def test_009_running_without_status_says_so():
    cfg = config.parse(yaml.safe_load("sessions: [{name: a, dir: /x, account: default}]"))
    out = ("@@TMUX\ncc-a|0|1000\n@@NOW\n{now}\n@@STATE\n@@HOOK\nyes\n@@END\n")
    st = sessions.resolve(cfg, cfg.sessions[0], sessions.parse_poll(out.format(now=1005)))
    assert st.state == "idle" and st.message == ""  # just started: hooks get a moment
    st = sessions.resolve(cfg, cfg.sessions[0], sessions.parse_poll(out.format(now=1060)))
    # no SessionStart after 15 s: Claude is stuck before the session (trust / login
    # screen, seen on real Claude): that needs you
    assert st.state == "waiting" and "login, trust" in st.message and "press u" in st.message
    # older poll output without the creation time still parses
    hp = sessions.parse_poll("@@TMUX\ncc-a|1\n@@STATE\n@@HOOK\nyes\n@@END\n")
    assert hp.tmux == {"a": True} and hp.age == {}


# ------------------------------------------------------------------ 032 non-POSIX login shell


@needs_tmux
@pytest.mark.parametrize("shell", ["/bin/tcsh", "/bin/zsh", "/bin/bash"])
def test_032_sessions_start_with_any_login_shell(env, monkeypatch, shell, capsys):
    import json
    from ccdeck import cli
    if not os.path.exists(shell):
        pytest.skip(f"{shell} not installed")
    monkeypatch.setenv("SHELL", shell)
    (env.home / "my proj").mkdir()  # a space in the path, too
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
accounts: {{work: {{config_dir: ~/.claude-work, env: {{CCDECK_TEST_VAR: "a b"}}}}}}
sessions: [{{name: shop, dir: "~/my proj", account: work}}]
""")
    # setup's claude check runs through the login shell too
    assert cli.main(["setup"]) == 0, capsys.readouterr()
    assert "claude" in capsys.readouterr().out
    assert cli.main(["start", "shop", "-d"]) == 0
    log = env.home / ".claude-work" / "fake-claude-runs.log"
    wait_for(log.exists, what=f"claude started under {shell}")
    run = json.loads(log.read_text().splitlines()[0])
    assert run["cwd"] == str(env.home / "my proj") and run["test_var"] == "a b"


# ------------------------------------------------------------------ 045 new account stays idle


@needs_tmux
def test_045_starting_a_session_sets_up_missing_hooks(env, capsys):
    """A new account whose hook setup never finished (console quit mid-setup): starting its
    session sets the hooks up first, so it gets a status instead of staying idle."""
    import json
    from ccdeck import cli
    (env.home / "proj").mkdir()
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
accounts: {{fresh: {{config_dir: ~/.claude-fresh}}}}
sessions: [{{name: p, dir: ~/proj, account: fresh}}]
""")
    cfg = config.load()
    assert not installer.hooks_present(cfg.hosts["local"], "~/.claude-fresh")
    assert cli.main(["start", "p", "-d"]) == 0
    assert installer.hooks_present(cfg.hosts["local"], "~/.claude-fresh")
    state = env.home / ".ccdeck" / "state" / "p.json"
    wait_for(state.exists, what="a status from the hooks")
    assert json.loads(state.read_text())["event"] == "SessionStart"
    # already set up: the next start doesn't run setup again
    cli.main(["stop", "p"])
    calls = []
    real = installer.setup_host
    installer.setup_host = lambda *a, **k: calls.append(a) or real(*a, **k)
    try:
        assert cli.main(["start", "p", "-d"]) == 0
    finally:
        installer.setup_host = real
    assert calls == []


def test_045_worker_commands_have_no_terminal(env):
    """Background commands run in their own session: an interactive login shell can't be
    stopped by (or take over) the console's terminal."""
    proc = remote.sh(config.Host("local"), "ps -o tty= -p $$")
    assert proc.stdout.strip() in ("?", "??")  # no controlling terminal


# ------------------------------------------------------------------ 046 cut-off hook.py


def _set_up_local(env):
    (env.home / "proj").mkdir(exist_ok=True)
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
sessions: [{{name: p, dir: ~/proj}}]
""")
    cfg = config.load()
    assert installer.setup_host(cfg, cfg.hosts["local"], False, lambda line: None)
    return cfg


def test_046_interrupted_upload_never_leaves_a_cut_off_hook(env):
    """Killing the upload halfway (console quit mid-setup) leaves the old hook.py or none,
    never half of the new one."""
    import signal
    import subprocess
    src = installer.hook_source()
    child = subprocess.Popen(["sh", "-c", installer.UPLOAD_SCRIPT], stdin=subprocess.PIPE,
                             text=True, start_new_session=True)
    child.stdin.write(src[: len(src) // 2])
    child.stdin.flush()
    time.sleep(0.5)
    os.killpg(child.pid, signal.SIGKILL)
    child.wait()
    hook_py = env.home / ".ccdeck" / "hook.py"
    assert not hook_py.exists() or hook_py.read_text() == src


@needs_tmux
def test_046_cut_off_hook_is_repaired_before_start(env):
    """A hook.py cut off by an earlier interrupted setup counted as installed, so every
    hook call failed and the session stayed idle. The check before a start now notices."""
    cfg = _set_up_local(env)
    hook_py = env.home / ".ccdeck" / "hook.py"
    src = hook_py.read_text()
    hook_py.write_text(src[: len(src) // 2])
    assert not installer.hooks_present(cfg.hosts["local"], "~/.claude")
    assert installer.ensure_hooks(cfg, cfg.hosts["local"], "~/.claude")
    assert hook_py.read_text() == src
    sessions.start(cfg, "p")
    wait_for((env.home / ".ccdeck" / "state" / "p.json").exists, what="a status")


# ------------------------------------------------------------------ 047 old hook.py on hosts


def test_047_older_hook_is_replaced_before_start(env, monkeypatch):
    """A host set up by an older ccdeck kept its old hook (old status logic) forever,
    unless you re-ran `ccdeck setup`. Starting a session now updates it."""
    from ccdeck import cli
    cfg = _set_up_local(env)
    hook_py = env.home / ".ccdeck" / "hook.py"
    hook_py.write_text(installer.hook_source().replace("def dump():", "def dump_old():"))
    assert not installer.hooks_present(cfg.hosts["local"], "~/.claude")
    calls = []
    # only the hook check matters here
    monkeypatch.setattr(sessions, "start", lambda *a, **k: calls.append(a))
    assert cli.main(["start", "p", "-d"]) == 0
    assert calls and hook_py.read_text() == installer.hook_source()
    assert installer.hooks_present(cfg.hosts["local"], "~/.claude")


# ------------------------------------------------------------------ 048 timeout leaves children


def test_048_timeout_kills_the_whole_command(env):
    """A timeout killed only `sh`/`ssh`; what it started (a login shell, python3) kept
    running. Now the whole process group goes."""
    import subprocess
    marker = "sleep 31.4159"
    try:
        proc = remote.sh(config.Host("local"), f"{marker}; echo never", timeout=1)
        assert proc.returncode == 255 and "timed out" in proc.stderr
        time.sleep(0.3)
        left = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
        assert left.stdout.strip() == ""
    finally:
        subprocess.run(["pkill", "-f", marker])


# ------------------------------------------------------------------ 049 env file after failed start


@needs_tmux
def test_049_failed_start_removes_the_env_file(env):
    """If tmux couldn't create the session, the account's env file (API key) was already
    written and nothing deleted it, since only the pane does."""
    import shutil
    real_tmux = shutil.which("tmux")
    (env.bin / "tmux").write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do [ "$a" = new-session ] && { echo "no space" >&2; exit 1; }; done\n'
        f'exec {real_tmux} "$@"\n')
    (env.bin / "tmux").chmod(0o755)
    (env.home / "proj").mkdir()
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
accounts: {{api: {{config_dir: ~/.claude-api, env: {{ANTHROPIC_API_KEY: sk-ant-xyz}}}}}}
sessions: [{{name: p, dir: ~/proj, account: api}}]
""")
    cfg = config.load()
    with pytest.raises(sessions.SessionError, match="no space"):
        sessions.start(cfg, "p")
    assert not (env.home / ".ccdeck" / "env" / "p.sh").exists()


# ------------------------------------------------------------------ 050 watch errors not logged


def test_050_watch_logs_poll_failures(env, monkeypatch):
    """`ccdeck watch` (often a background service) only printed poll errors to stderr."""
    from ccdeck import cli, log as log_mod
    env.write_config("sessions: [{name: p, dir: /tmp}]\n")

    def boom(cfg):
        raise RuntimeError("kaboom")

    def stop(secs):
        raise KeyboardInterrupt

    monkeypatch.setattr(sessions, "poll", boom)
    monkeypatch.setattr(time, "sleep", stop)
    try:
        assert cli.main(["watch"]) == 0
    finally:
        notify.release_watch_lock()
    assert "watch: poll failed: kaboom" in log_mod.tail(50)


# ------------------------------------------------------------------ 055 Enter swallowed after text


def test_055_key_after_text_goes_in_its_own_burst(env, monkeypatch):
    """Real Claude (2.1.316) read 81 characters + Enter in one write as a paste and didn't
    submit; a separate Enter 30 ms later did."""
    calls = []
    monkeypatch.setattr(remote, "run", lambda host, argv, **k: calls.append(argv) or
                        __import__("subprocess").CompletedProcess(argv, 0, "", ""))
    monkeypatch.setattr(sessions, "KEY_AFTER_TEXT_GAP", 0)
    env.write_config("sessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    sessions.send_input(cfg, "a", [("text", "x" * 81), ("key", "Enter")])
    assert len(calls) == 2 and calls[0][-1] == "x" * 81 and calls[1][-1] == "Enter"
    calls.clear()
    sessions.send_input(cfg, "a", [("key", "Up"), ("key", "Enter"), ("text", "ab")])
    assert len(calls) == 1  # keys and text after them: still one call
    calls.clear()
    sessions.send_input(cfg, "a", [("paste", "p"), ("key", "Enter"), ("text", "q"),
                                   ("key", "Tab")])
    assert len(calls) == 3

