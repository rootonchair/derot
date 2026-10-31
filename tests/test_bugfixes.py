"""Regression tests for tracking/ items 001-008."""

import json
import os
import subprocess
import sys
import time

import pytest

from derot import cli, config, hook, notify, sessions
from derot.config import Notify
from derot.sessions import Status

from .conftest import needs_tmux, wait_for


def write(env, sessions_yaml, accounts="personal: {config_dir: ~/.claude}"):
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
accounts: {{{accounts}}}
sessions:
{sessions_yaml}
""")


def by_name(cfg):
    return {st.name: st for st in sessions.poll(cfg)}


@pytest.fixture
def ready(env, capsys):
    """Config with hooks installed and project folders created."""
    def make(sessions_yaml, folders=("p",), **kw):
        for f in folders:
            (env.home / f).mkdir(exist_ok=True)
        write(env, sessions_yaml, **kw)
        cli.main(["setup"])
        capsys.readouterr()
        return config.load()
    return make


# ---------------------------------------------------------------- 001 / 002

@needs_tmux
def test_001_stop_never_hits_a_prefix_match(env, ready, capsys):
    cfg = ready("  - {name: api, dir: ~/p}\n  - {name: api-v2, dir: ~/p}")
    assert cli.main(["start", "api-v2", "-d"]) == 0
    capsys.readouterr()
    assert cli.main(["stop", "api"]) == 1
    assert "not running" in capsys.readouterr().err
    assert env.tmux("has-session", "-t", "=cc-api-v2").returncode == 0  # still alive
    assert by_name(cfg)["api-v2"].running and not by_name(cfg)["api"].running
    # attach targets are exact too
    assert env.tmux("has-session", "-t", sessions.target("api")).returncode != 0


@needs_tmux
def test_002_dotted_names_work(env, ready, capsys):
    cfg = ready("  - {name: next.js-site, dir: ~/p}")
    assert cli.main(["start", "next.js-site", "-d"]) == 0
    wait_for(lambda: by_name(cfg)["next.js-site"].state == "idle", what="idle")
    assert env.tmux("has-session", "-t", sessions.target("next.js-site")).returncode == 0
    assert cli.main(["stop", "next.js-site"]) == 0
    assert not by_name(cfg)["next.js-site"].running


# ---------------------------------------------------------------- 003

@needs_tmux
def test_003_starting_a_running_session_keeps_its_status(env, ready, capsys):
    cfg = ready("  - {name: a, dir: ~/p}")
    cli.main(["start", "a", "-d"])
    env.send("a", "do it")
    wait_for(lambda: by_name(cfg)["a"].state == "waiting", what="waiting")
    env.send("a", "")
    st = wait_for(lambda: (s := by_name(cfg)["a"]).state == "done" and s, what="done")
    capsys.readouterr()
    assert cli.main(["start", "a", "-d"]) == 1
    assert "already running" in capsys.readouterr().err
    again = by_name(cfg)["a"]
    assert (again.state, again.message, again.prompt) == ("done", st.message, "do it")


# ---------------------------------------------------------------- 004

@needs_tmux
def test_004_declined_permission_leaves_needs_you(env, ready):
    cfg = ready("  - {name: a, dir: ~/p}")
    cli.main(["start", "a", "-d"])
    env.send("a", "rm stuff")
    wait_for(lambda: by_name(cfg)["a"].state == "waiting", what="waiting")
    env.send("a", "n")  # decline: real Claude Code fires no hook for this
    st = wait_for(lambda: (s := by_name(cfg)["a"]).state == "idle" and s, what="idle")
    assert st.message == "you declined the request"


@needs_tmux
def test_004_esc_interrupt_leaves_needs_you(env, ready):
    cfg = ready("  - {name: a, dir: ~/p}")
    cli.main(["start", "a", "-d"])
    env.send("a", "long job")
    wait_for(lambda: by_name(cfg)["a"].state == "waiting", what="waiting")
    env.send("a", "esc")
    st = wait_for(lambda: (s := by_name(cfg)["a"]).state == "idle" and s, what="idle")
    assert st.message == "interrupted"


def test_004_reconcile_without_newer_events(tmp_path):
    """Older Claude Code: no PostToolUseFailure, so the transcript marker is what clears it."""
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use"}]}})
                 + "\n")
    state = {"state": "busy", "ts": time.time() - 5, "transcript_path": str(t)}
    assert hook.reconcile(dict(state))["state"] == "busy"  # nothing new yet
    with open(t, "a") as f:
        f.write(json.dumps({"type": "user", "message": {"content": [
            {"type": "text", "text": "[Request interrupted by user]"}]}}) + "\n")
    assert hook.reconcile(dict(state))["state"] == "idle"
    # a stale transcript (older than the last hook event) is ignored
    assert hook.reconcile(dict(state, ts=time.time() + 60))["state"] == "busy"


# ---------------------------------------------------------------- 005

@needs_tmux
def test_005_config_is_private(env):
    assert cli.main(["init"]) == 0
    assert env.config.stat().st_mode & 0o777 == 0o600
    cfg = config.load()
    cfg.accounts["personal"].env = {"ANTHROPIC_API_KEY": "sk-ant-x"}
    config.save(cfg)
    assert env.config.stat().st_mode & 0o777 == 0o600
    assert env.config.with_name("config.yaml.bak").stat().st_mode & 0o777 == 0o600


# ---------------------------------------------------------------- 006

def run_hook(home, event, payload):
    env = dict(os.environ, HOME=str(home), DEROT_SESSION="s")
    subprocess.run([sys.executable, hook.__file__, event], input=json.dumps(payload),
                   capture_output=True, text=True, env=env, check=True)
    return json.loads((home / ".derot" / "state" / "s.json").read_text())


def test_006_child_claude_does_not_overwrite_parent(tmp_path):
    st = run_hook(tmp_path, "SessionStart", {"session_id": "parent", "source": "startup"})
    assert st["session_id"] == "parent"
    run_hook(tmp_path, "UserPromptSubmit", {"session_id": "parent", "prompt": "build it"})
    # a `claude -p` started from inside the session inherits DEROT_SESSION:
    st = run_hook(tmp_path, "SessionStart", {"session_id": "child", "source": "startup"})
    st = run_hook(tmp_path, "Stop", {"session_id": "child", "last_assistant_message": "x"})
    assert (st["session_id"], st["state"], st["prompt"]) == ("parent", "busy", "build it")
    # /clear in the real session switches to a new id
    st = run_hook(tmp_path, "SessionStart", {"session_id": "after-clear", "source": "clear"})
    assert st["session_id"] == "after-clear" and st["state"] == "idle"
    st = run_hook(tmp_path, "Stop", {"session_id": "after-clear", "last_assistant_message": "ok"})
    assert (st["state"], st["message"]) == ("done", "ok")


# ---------------------------------------------------------------- 007

def statuses(cfg, **states):
    out = []
    for s in cfg.sessions:
        spec = states[s.name]
        state, attached = (spec, False) if isinstance(spec, str) else spec
        out.append(Status(s, cfg.host_of(s), cfg.account_of(s), state=state, attached=attached))
    return out


def two_session_cfg():
    return config.parse({"hosts": {"vm": {"ssh": "vm"}},
                         "sessions": [{"name": "a", "dir": "/a"},
                                      {"name": "b", "host": "vm", "dir": "/b"}]})


def test_007_no_alert_when_attached_or_back_online(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda t, b, s="": sent.append(t))
    cfg = two_session_cfg()
    n = notify.Notifier(Notify())
    n.update(statuses(cfg, a="busy", b="waiting"))
    n.update(statuses(cfg, a=("waiting", True), b="waiting"))  # attached: no alert
    assert sent == []
    n.update(statuses(cfg, a="busy", b="offline"))
    n.update(statuses(cfg, a="busy", b="waiting"))  # back online, still waiting: no re-alert
    assert sent == []
    n.update(statuses(cfg, a="done", b="waiting"))
    assert sent == ["a finished"]


def test_007_console_leaves_desktop_alerts_to_watch(env, monkeypatch):
    sent, toasts = [], []
    monkeypatch.setattr(notify, "send", lambda t, b, s="": sent.append(t))
    cfg = two_session_cfg()
    # another `derot watch` holds the lock (a real separate process)
    holder = subprocess.Popen(
        [sys.executable, "-c", "import sys, time; from derot import notify; "
         "assert notify.acquire_watch_lock(); print('locked', flush=True); time.sleep(60)"],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        n = notify.Notifier(Notify(), toast=lambda t, b: toasts.append(t), defer_to_watch=True)
        n.update(statuses(cfg, a="busy", b="idle"))
        n.update(statuses(cfg, a="waiting", b="idle"))
        assert sent == [] and toasts == ["a needs you"]
        assert not notify.acquire_watch_lock()  # a second watch refuses to start
    finally:
        holder.terminate()  # 039: killed, no cleanup ran - the lock still goes with it
        holder.wait()
    assert notify.watch_lock().exists()
    assert not notify.watch_running()
    try:
        assert notify.acquire_watch_lock()
        assert not notify.watch_running()  # holding it ourselves isn't "another watch"
    finally:
        notify.release_watch_lock()


# ---------------------------------------------------------------- 008

@needs_tmux
def test_008_absolute_default_folder_keeps_normal_login(env, ready):
    absolute = str(env.home / ".claude")
    cfg = ready("  - {name: a, dir: ~/p, account: me}", accounts=f'me: {{config_dir: "{absolute}"}}')
    assert cfg.accounts["me"].is_default_dir
    cli.main(["start", "a", "-d"])
    log = env.home / ".claude" / "fake-claude-runs.log"
    run = wait_for(lambda: log.exists() and json.loads(log.read_text().splitlines()[-1]),
                   what="fake claude run")
    assert run["config_dir_env"] is None


def test_notifications_are_brief(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda t, b, s="": sent.append((t, b)))
    long_reply = ("Done. I refactored the payment module, added 14 tests, updated the docs "
                  "and fixed three flaky checkout tests along the way. " * 5)
    assert notify.brief(long_reply) == "Done."
    no_sentence = "word " * 60
    b = notify.brief(no_sentence)
    assert len(b) <= notify.MAX_BODY and b.endswith("…") and "  " not in b
    cfg = two_session_cfg()
    n = notify.Notifier(Notify())
    n.update(statuses(cfg, a="busy", b="idle"))
    sts = statuses(cfg, a="done", b="idle")
    sts[0].message = "Refactored checkout validation and added tests for the error states: " + "x" * 300
    n.update(sts)
    assert sent == [("a finished", "Refactored checkout validation and added tests for the error states")]


# ---------------------------------------------------------------- bug hunt (tracking 022-028)

@needs_tmux
def test_022_replies_starting_with_dash_are_sent(env, ready):
    cfg = ready("  - {name: a, dir: ~/p}")
    cli.main(["start", "a", "-d"])
    wait_for(lambda: by_name(cfg)["a"].state == "idle", what="idle")
    for text in ("- fix it", "-1", "--"):
        sessions.send_input(cfg, "a", [("text", text), ("key", "Enter")])
        # the hook records what Claude received as the prompt
        st = wait_for(lambda: (x := by_name(cfg)["a"]).state == "waiting" and x,
                      what=f"{text!r} received")
        assert st.prompt == text
        env.send("a", "")  # approve the fake's prompt so it's ready for the next line
        wait_for(lambda: by_name(cfg)["a"].state == "done", what="done")


@needs_tmux
def test_023_dollar_home_paths_work(env, ready):
    cfg = ready('  - {name: a, dir: "$HOME/p", account: w}', accounts='w: {config_dir: "${HOME}/.cw"}')
    assert cfg.session("a").dir == "~/p" and cfg.accounts["w"].config_dir == "~/.cw"
    assert config.parse({"accounts": {"x": {"config_dir": "$HOME/.claude"}},
                         "sessions": [{"name": "a", "dir": "/x"}]}).accounts["x"].is_default_dir
    cli.main(["start", "a", "-d"])
    log = env.home / ".cw" / "fake-claude-runs.log"
    run = wait_for(lambda: log.exists() and json.loads(log.read_text().splitlines()[-1]),
                   what="fake claude run")
    assert run["config_dir_env"] == str(env.home / ".cw")
    assert run["cwd"] == str(env.home / "p")


def test_024_attach_does_not_chain_on_window_size(monkeypatch, env):
    """tmux < 2.9 has no window-size; a failing command in a `;` chain would stop attach."""
    env.write_config("sessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    calls = []
    monkeypatch.setattr(sessions.remote, "run",
                        lambda host, argv, **kw: calls.append(("run", argv)) or
                        subprocess.CompletedProcess(argv, 1, "", "invalid option: window-size"))
    monkeypatch.setattr(sessions.remote, "interactive",
                        lambda host, argv: calls.append(("attach", argv)) or 0)
    monkeypatch.setattr(sessions, "mark_seen", lambda cfg, name: None)
    assert sessions.attach(cfg, "a") == 0
    attach_argv = [argv for kind, argv in calls if kind == "attach"][0]
    assert ";" not in attach_argv and "window-size" not in attach_argv


def test_025_idle_reminder_keeps_pending_prompt():
    st = {"state": "waiting", "message": "wants to use Bash: rm -rf build"}
    out = hook.apply(dict(st), "Notification", {"message": "Claude is waiting for your input",
                                                "notification_type": "idle_prompt"})
    assert (out["state"], out["message"]) == ("waiting", "wants to use Bash: rm -rf build")


def test_026_no_alert_for_state_first_seen_after_offline_start(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda t, b, s="": sent.append(t))
    cfg = two_session_cfg()
    n = notify.Notifier(Notify())
    n.update(statuses(cfg, a="busy", b="offline"))   # console starts while vm is down
    n.update(statuses(cfg, a="busy", b="waiting"))   # vm back: b was already waiting
    assert sent == []
    n.update(statuses(cfg, a="busy", b="busy"))
    n.update(statuses(cfg, a="busy", b="waiting"))   # a real new prompt still alerts
    assert sent == ["b needs you"]


def test_027_names_cannot_start_with_dot():
    with pytest.raises(config.ConfigError):
        config.parse({"sessions": [{"name": ".hidden", "dir": "/x"}]})
    assert config.parse({"sessions": [{"name": "next.js", "dir": "/x"}]}).sessions


@needs_tmux
async def test_028_preview_refits_after_outside_resize(env, ready, capsys):
    from derot.tui import Derot
    ready("  - {name: a, dir: ~/p}")
    cli.main(["start", "a", "-d"])
    app = Derot(config.load())
    app.preview_mode = "screen"

    def size():
        return env.tmux("display", "-p", "-t", "=cc-a:", "#{window_width}").stdout.strip()

    async with app.run_test(size=(150, 40)) as pilot:
        for _ in range(50):
            await pilot.pause(0.2)
            if size() == str(app.query_one("#preview-box").content_region.width):
                break
        width = str(app.query_one("#preview-box").content_region.width)
        assert size() == width
        # someone else resizes it (an attach from another terminal, a restart, ...)
        env.tmux("resize-window", "-t", "=cc-a:", "-x", "200", "-y", "50")
        for _ in range(50):
            await pilot.pause(0.2)
            if size() == width:
                break
        assert size() == width
