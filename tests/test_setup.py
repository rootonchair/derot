import json

from derot import cli, installer

from .conftest import needs_tmux

CONFIG = """
hosts:
  local: {claude: "@CLAUDE@"}
  vm: {ssh: me@vm, claude: "@CLAUDE@"}
  dead: {ssh: deadvm}
accounts:
  personal: {config_dir: ~/.claude}
  work: {config_dir: ~/.claude-work}
sessions:
  - {name: a, host: local, dir: ~/a, account: personal}
  - {name: b, host: local, dir: ~/b, account: work}
  - {name: c, host: vm, dir: ~/c, account: work}
  - {name: d, host: dead, dir: ~/d, account: work}
"""

USER_SETTINGS = {
    "model": "opus",
    "permissions": {"allow": ["Bash(ls:*)"]},
    "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
        "PreToolUse": [{"matcher": "Edit", "hooks": [{"type": "command", "command": "lint"}]}],
    },
}


def derot_cmds(settings):
    out = []
    for ev, groups in settings.get("hooks", {}).items():
        for g in groups:
            for h in g["hooks"]:
                if "/.derot/hook.py" in h["command"]:
                    out.append((ev, g.get("matcher"), h["command"]))
    return out


@needs_tmux
def test_setup_install_idempotent_and_remove(env, capsys):
    env.write_config(CONFIG)
    personal = env.home / ".claude" / "settings.json"
    env.write_json(personal, USER_SETTINGS)
    original = personal.read_text()

    assert cli.main(["setup"]) == 1  # dead host fails
    out = capsys.readouterr().out
    assert "can't reach it: ssh: connect to host deadvm port 22: Connection refused" in out
    assert "✓ tmux" in out and "✓ hook installed" in out

    # hook file on both hosts
    assert (env.home / ".derot" / "hook.py").exists()
    assert (env.vm_home() / ".derot" / "hook.py").exists()
    assert (env.vm_home() / ".derot" / "state").is_dir()

    files = [personal, env.home / ".claude-work" / "settings.json",
             env.vm_home() / ".claude-work" / "settings.json"]
    for f in files:
        s = json.loads(f.read_text())
        cmds = derot_cmds(s)
        assert len(cmds) == 10, f  # 7 core + 3 newer events the fake claude supports
        assert ("PreToolUse", "*", "python3 ~/.derot/hook.py PreToolUse") in cmds
        assert ("PermissionRequest", "*", "python3 ~/.derot/hook.py PermissionRequest") in cmds
        assert ("StopFailure", None, "python3 ~/.derot/hook.py StopFailure") in cmds
        assert ("Stop", None, "python3 ~/.derot/hook.py Stop") in cmds
    # VM's personal account isn't used there
    assert not (env.vm_home() / ".claude").exists()

    s = json.loads(personal.read_text())
    assert s["model"] == "opus" and s["permissions"] == USER_SETTINGS["permissions"]
    assert {"type": "command", "command": "say done"} in s["hooks"]["Stop"][0]["hooks"]
    assert s["hooks"]["PreToolUse"][0]["matcher"] == "Edit"
    assert (personal.parent / "settings.json.derot-bak").read_text() == original

    # second run: no duplicates
    cli.main(["setup"])
    capsys.readouterr()
    for f in files:
        assert len(derot_cmds(json.loads(f.read_text()))) == 10

    # remove: back to exactly the original settings
    assert cli.main(["setup", "--remove"]) == 1  # dead host still unreachable
    assert json.loads(personal.read_text()) == USER_SETTINGS
    assert list(json.loads(personal.read_text())["hooks"]) == ["Stop", "PreToolUse"]
    for f in files[1:]:
        assert json.loads(f.read_text()) == {}


@needs_tmux
def test_setup_refuses_invalid_json(env, capsys):
    env.write_config(CONFIG.replace("  - {name: d, host: dead, dir: ~/d, account: work}\n", ""))
    bad = env.home / ".claude" / "settings.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{not json")
    assert cli.main(["setup"]) == 1
    out = capsys.readouterr().out
    assert "is not valid JSON" in out
    assert bad.read_text() == "{not json"


@needs_tmux
def test_setup_reports_missing_claude(env, capsys):
    env.write_config(CONFIG.replace('local: {claude: "@CLAUDE@"}', "local: {claude: no-such-claude}")
                     .replace("  - {name: d, host: dead, dir: ~/d, account: work}\n", ""))
    assert cli.main(["setup"]) == 1
    assert "claude not found" in capsys.readouterr().out


@needs_tmux
def test_older_claude_gets_only_core_events(env, capsys):
    old = env.bin / "old-claude"
    old.write_text("#!/bin/sh\necho old claude\n")  # knows none of the newer event names
    old.chmod(0o755)
    env.write_config(f"""
hosts: {{local: {{claude: "{old}"}}}}
sessions: [{{name: a, dir: ~/a}}]
""")
    assert cli.main(["setup"]) == 0
    s = json.loads((env.home / ".claude" / "settings.json").read_text())
    assert sorted(ev for ev, _, _ in derot_cmds(s)) == sorted(installer.EVENTS)

    # upgrading claude later and re-running setup adds the extras without duplicates
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
sessions: [{{name: a, dir: ~/a}}]
""")
    assert cli.main(["setup"]) == 0
    s = json.loads((env.home / ".claude" / "settings.json").read_text())
    assert len(derot_cmds(s)) == 10
    assert cli.main(["setup", "--remove"]) == 0
    assert "hooks" not in json.loads((env.home / ".claude" / "settings.json").read_text())
