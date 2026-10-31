import json
import os
import pty
import subprocess
import sys

import pytest

from ccdeck import cli, config, remote, sessions

from .conftest import needs_tmux, wait_for

pytestmark = needs_tmux

CONFIG = """
hosts:
  local: {claude: "@CLAUDE@"}
  vm: {ssh: me@vm, claude: "@CLAUDE@"}
  dead: {ssh: deadvm}
accounts:
  personal: {config_dir: ~/.claude}
  work: {config_dir: ~/.claude-work, env: {CCDECK_TEST_VAR: hello world, "bad-key": x}}
sessions:
  - {name: shop, host: local, dir: ~/proj/shop, account: personal, note: payments}
  - {name: api, host: vm, dir: ~/proj/api, account: work}
  - {name: gone, host: dead, dir: ~/x, account: work}
"""


@pytest.fixture
def deck(env, capsys):
    env.write_config(CONFIG)
    (env.home / "proj" / "shop").mkdir(parents=True)
    (env.vm_home() / "proj" / "api").mkdir(parents=True)
    cli.main(["setup"])
    capsys.readouterr()
    return env


def runs(cdir):
    log = cdir / "fake-claude-runs.log"
    if not log.exists():
        return []
    return [json.loads(ln) for ln in log.read_text().splitlines()]


def by_name(statuses):
    return {st.name: st for st in statuses}


def ls_rows(capsys):
    capsys.readouterr()
    assert cli.main(["ls"]) == 0
    out = capsys.readouterr().out.splitlines()
    return out[1:]


def test_start_local_and_vm_with_accounts(deck, capsys):
    assert cli.main(["start", "shop", "-d"]) == 0
    assert cli.main(["start", "api", "-d", "-c"]) == 0
    r_shop = wait_for(lambda: runs(deck.home / ".claude"), what="local claude")
    r_api = wait_for(lambda: runs(deck.vm_home() / ".claude-work"), what="vm claude")
    assert r_shop[0]["args"] == [] and r_shop[0]["session"] == "shop"
    assert r_shop[0]["cwd"] == str(deck.home / "proj" / "shop")
    assert r_shop[0]["config_dir_env"] is None  # default account: normal login untouched
    assert r_api[0]["args"] == ["--continue"]
    assert r_api[0]["cwd"] == str(deck.vm_home() / "proj" / "api")
    assert r_api[0]["config_dir_env"] == str(deck.vm_home() / ".claude-work")
    assert r_api[0]["test_var"] == "hello world"  # account env reaches claude
    assert "account=" + str(deck.vm_home() / ".claude-work") in deck.pane("api", host="vm")

    assert cli.main(["start", "shop", "-d"]) == 1
    assert "`shop` is already running" in capsys.readouterr().err

    # secrets: passed in a 0600 env file the pane reads and deletes, never on its command
    # line, and not left on the host's disk afterwards
    env_file = deck.vm_home() / ".ccdeck" / "env" / "api.sh"
    assert not env_file.exists() and not (deck.home / ".ccdeck" / "env" / "shop.sh").exists()
    cfg = config.load()
    content = sessions.env_content(cfg.account_of(cfg.session("api")))
    assert "CCDECK_TEST_VAR='hello world'" in content and "bad-key" not in content
    proc = remote.sh(config.Host("local"), sessions.write_env_script("probe"), input=content)
    assert proc.returncode == 0
    written = deck.home / ".ccdeck" / "env" / "probe.sh"
    assert written.stat().st_mode & 0o777 == 0o600 and written.read_text() == content
    assert "hello world" not in sessions.start_script(cfg, cfg.session("api"))
    assert sessions.env_content(cfg.account_of(cfg.session("api"))) not in sessions.pane_cmd(
        cfg, cfg.session("api"))


def test_status_flow_and_sorting(deck, capsys):
    cli.main(["start", "shop", "-d"])
    cli.main(["start", "api", "-d"])
    cfg = config.load()

    def state(name):
        return by_name(sessions.poll(cfg))[name]

    wait_for(lambda: state("shop").state == "idle" and state("shop").message == "",
             what="shop idle")
    st = state("gone")
    assert st.state == "offline" and "Connection refused" in st.message

    deck.send("shop", "fix the login bug")
    st = wait_for(lambda: (s := state("shop")).state == "waiting" and s, what="shop waiting")
    assert st.message == "wants to use Bash: ls"
    assert st.prompt == "fix the login bug"

    rows = ls_rows(capsys)
    assert rows[0].split()[:2] == ["◆", "shop"] and "needs you" in rows[0]
    assert "wants to use Bash: ls" in rows[0]

    deck.send("shop", "")  # approve
    st = wait_for(lambda: (s := state("shop")).state == "done" and s, what="shop done")
    assert st.message == "All done with: fix the login bug"

    # waiting sorts above done, offline last
    deck.send("api", "ship it", host="vm")
    wait_for(lambda: state("api").state == "waiting", what="api waiting")
    order = [s.name for s in sessions.poll(cfg)]
    assert order == ["api", "shop", "gone"]
    rows = ls_rows(capsys)
    assert "needs you" in rows[0] and "done" in rows[1] and "All done with" in rows[1]
    assert "offline" in rows[2]

    # stop: session shows stopped with the last reply
    assert cli.main(["stop", "shop"]) == 0
    st = state("shop")
    assert st.state == "stopped" and st.message == "All done with: fix the login bug"
    assert cli.main(["stop", "shop"]) == 1
    assert "not running" in capsys.readouterr().err


def test_idle_without_hooks(env, capsys):
    """A session running without the hook script (e.g. started outside ccdeck) says so;
    `ccdeck start` itself sets missing hooks up first (test_045)."""
    env.write_config(CONFIG)
    (env.home / "proj" / "shop").mkdir(parents=True)
    cfg = config.load()
    script = sessions.start_script(cfg, cfg.session("shop"))
    assert remote.sh(cfg.hosts["local"], script).returncode == 0  # no hook setup
    st = wait_for(lambda: by_name(sessions.poll(cfg))["shop"], what="poll")
    assert st.state == "idle" and "ccdeck setup" in st.message


def test_missing_dir_fails_the_start(deck, capsys):
    """Checked before the session is created, so the error shows where you started it
    (also for a folder on a VM) instead of in a pane you have to open."""
    deck.write_config(CONFIG.replace("~/proj/shop", "~/nope").replace("~/proj/api", "~/gone"))
    assert cli.main(["start", "shop", "-d"]) == 1
    assert "folder not found: ~/nope" in capsys.readouterr().err
    assert cli.main(["start", "api", "-d"]) == 1
    assert "folder not found: ~/gone" in capsys.readouterr().err
    assert deck.tmux("has-session", "-t", "=cc-shop:").returncode != 0


def test_attach_then_detach_marks_seen(deck):
    cli.main(["start", "shop", "-d"])
    cfg = config.load()
    deck.send("shop", "hello")
    wait_for(lambda: by_name(sessions.poll(cfg))["shop"].state == "waiting", what="waiting")
    deck.send("shop", "")
    wait_for(lambda: by_name(sessions.poll(cfg))["shop"].state == "done", what="done")

    pid, fd = pty.fork()
    if pid == 0:  # child: run `ccdeck attach shop` on a real tty
        os.environ["TERM"] = "xterm-256color"
        os.execv(sys.executable, [sys.executable, "-m", "ccdeck", "attach", "shop"])
    try:
        wait_for(lambda: by_name(sessions.poll(cfg))["shop"].attached, what="attached")
        assert deck.tmux("detach-client", "-s", "cc-shop").returncode == 0
        _, status = os.waitpid(pid, 0)
    finally:
        os.close(fd)
    assert os.waitstatus_to_exitcode(status) == 0
    st = by_name(sessions.poll(cfg))["shop"]
    assert st.state == "idle" and not st.attached
    assert st.message == "All done with: hello"


def test_poll_script_parsing():
    out = "\n".join([
        "@@TMUX", "cc-a|1", "cc-b|0", "@@STATE",
        json.dumps({"session": "a", "state": "busy"}), "", "{broken", "@@HOOK", "yes", "@@END",
    ])
    hp = sessions.parse_poll(out)
    assert hp.tmux == {"a": True, "b": False}
    assert hp.states["a"]["state"] == "busy" and hp.hook
    assert sessions.parse_poll("@@TMUX\n") is None


def test_qpath():
    from ccdeck.remote import qpath
    assert qpath("~/x y") == "\"$HOME\"/'x y'"
    assert qpath("~") == '"$HOME"'
    assert qpath("/a b") == "'/a b'"
    out = subprocess.run(["sh", "-c", f"echo {qpath('~/a b')}"], capture_output=True, text=True,
                         env={"HOME": "/h"}).stdout.strip()
    assert out == "/h/a b"
