import json
import os
import subprocess
import sys

from derot import cli, config, hook, log as log_mod, sessions
from derot.log import redact
from derot.tui import Derot

from .conftest import needs_tmux


def test_redact_hides_keys():
    text = "export ANTHROPIC_API_KEY='sk-ant-abc123' && TOKEN=xyz use sk-ant-zzz9"
    out = redact(text)
    assert "abc123" not in out and "xyz" not in out and "zzz9" not in out
    assert "ANTHROPIC_API_KEY=***" in out and "TOKEN=***" in out


def test_unreachable_host_logged_once_with_full_error(env):
    env.write_config("hosts: {dead: {ssh: deadvm}}\nsessions: [{name: x, host: dead, dir: /x}]\n")
    log_mod.setup()
    sessions._online.clear()
    cfg = config.load()
    for _ in range(3):
        sessions.poll(cfg)
    text = log_mod.log_path().read_text()
    assert text.count("host dead is unreachable") == 1
    assert "Connection refused" in text


@needs_tmux
def test_start_failure_and_actions_logged(env, capsys):
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
accounts: {{work: {{config_dir: ~/.cw, env: {{ANTHROPIC_API_KEY: sk-ant-secret1}}}}}}
sessions: [{{name: a, dir: ~/a, account: work}}]
""")
    (env.home / "a").mkdir()
    os.environ["DEROT_DEBUG"] = "1"
    try:
        assert cli.main(["start", "a", "-d"]) == 0
        assert cli.main(["start", "a", "-d"]) == 1
        assert cli.main(["stop", "a"]) == 0
    finally:
        del os.environ["DEROT_DEBUG"]
    text = log_mod.log_path().read_text()
    assert "starting a on local (account work" in text
    assert "a is already running" in text and "stopping a on local" in text
    assert "rc=0" in text  # debug: commands logged
    assert "sk-ant-secret1" not in text  # API key never written to the log

    capsys.readouterr()
    assert cli.main(["log", "-n", "5"]) == 0
    assert "stopping a" in capsys.readouterr().out


def test_unexpected_cli_error_logged_with_traceback(env, monkeypatch, capsys):
    env.write_config("sessions: [{name: a, dir: /x}]\n")

    def boom(cfg):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(sessions, "poll_full", boom)
    assert cli.main(["ls"]) == 1
    assert "kaboom" in capsys.readouterr().err
    text = log_mod.log_path().read_text()
    assert "unexpected error in `derot ls`" in text and "Traceback" in text


async def test_error_toasts_are_logged(env):
    env.write_config("sessions: []\n")
    log_mod.setup()
    app = Derot(config.load(), poll_on_mount=False)
    async with app.run_test() as pilot:
        app.notify("hook setup on vm failed: python3 not found", severity="error")
        app.notify("just info")
        await pilot.pause()
    text = log_mod.log_path().read_text()
    assert "ERROR" in text and "hook setup on vm failed: python3 not found" in text
    assert "just info" not in text


def test_hook_errors_go_to_hook_log_not_stdout(tmp_path):
    state = tmp_path / ".derot" / "state"
    state.mkdir(parents=True)
    state.chmod(0o500)  # read-only: writing the state file fails
    try:
        env = dict(os.environ, HOME=str(tmp_path), DEROT_SESSION="s1")
        p = subprocess.run([sys.executable, hook.__file__, "Stop"], input=json.dumps({}),
                           capture_output=True, text=True, env=env)
    finally:
        state.chmod(0o700)
    assert p.returncode == 0 and p.stdout == ""
    errors = (tmp_path / ".derot" / "hook-errors.log").read_text()
    assert "session=s1" in errors and "Traceback" in errors
