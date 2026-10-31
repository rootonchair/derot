"""Codex support: accounts with `agent: codex`, its hooks.json, status, resume and login."""

import json

import pytest
from textual.widgets import Input, Select

from derot import cli, config, installer, remote, sessions
from derot.forms import AccountForm
from derot.tui import Derot

from .conftest import needs_tmux, wait_for


def codex_config(env, extra_sessions=""):
    (env.home / "app").mkdir(exist_ok=True)
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}", codex: "{env.codex}"}}}}
accounts:
  me: {{config_dir: ~/.claude}}
  oa: {{agent: codex, config_dir: ~/.codex-work}}
sessions:
  - {{name: app, dir: ~/app, account: oa}}{extra_sessions}
""")
    return config.load()


def runs(env):
    log = env.home / ".codex-work" / "fake-codex-runs.log"
    return [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []


def status(cfg, name="app"):
    return {st.name: st for st in sessions.poll(cfg)}[name]


def test_codex_accounts_in_the_config():
    cfg = config.parse({"accounts": {"oa": {"agent": "codex"}}, "sessions": []})
    oa = cfg.accounts["oa"]
    assert (oa.agent, oa.config_dir, oa.dir_env, oa.is_default_dir) == (
        "codex", "~/.codex", "CODEX_HOME", True)
    assert config.to_dict(cfg)["accounts"] == {"oa": {"agent": "codex", "config_dir": "~/.codex"}}
    lines = "\n".join(sessions.env_lines(oa, "x"))
    assert '= "$HOME/.codex" ]; then unset CODEX_HOME; else export CODEX_HOME=' in lines
    with pytest.raises(config.ConfigError, match="unknown agent 'gpt'"):
        config.parse({"accounts": {"x": {"agent": "gpt"}}})


def test_setup_writes_codex_hooks_json(env, capsys):
    cfg = codex_config(env)
    hooks = env.home / ".codex-work" / "hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "my-own-hook"}]}]}}))
    assert cli.main(["setup"]) == 0
    out = capsys.readouterr().out
    assert "✓ codex (" in out and "approve them" in out and "/hooks" in out
    data = json.loads(hooks.read_text())["hooks"]
    assert set(data) == set(installer.CODEX_EVENTS)
    assert "Notification" not in data
    stop = [h["command"] for g in data["Stop"] for h in g["hooks"]]
    assert stop == ["my-own-hook", "python3 ~/.derot/hook.py Stop"]  # yours are kept
    assert data["Interrupt"][0]["hooks"][0]["timeout"] == 3  # Codex's cap
    assert not (env.home / ".codex-work" / "settings.json").exists()
    assert installer.hooks_present(cfg.hosts["local"], "~/.codex-work", "codex")
    assert cli.main(["setup", "--remove"]) == 0
    assert json.loads(hooks.read_text())["hooks"] == {"Stop": [{"hooks": [
        {"type": "command", "command": "my-own-hook"}]}]}


@needs_tmux
def test_codex_session_status_flow(env, capsys):
    cfg = codex_config(env)
    cli.main(["setup"])
    assert cli.main(["start", "app", "-d"]) == 0
    capsys.readouterr()
    wait_for(lambda: runs(env), what="codex started")
    assert runs(env)[0]["codex_home_env"] == str(env.home / ".codex-work")
    assert runs(env)[0]["args"] == []
    assert status(cfg).state == "idle"  # Codex says nothing until the first prompt

    env.send("app", "fix the tests")
    st = wait_for(lambda: status(cfg).state == "waiting" and status(cfg), what="approval")
    assert st.message == "wants to use shell: bash -lc ls"
    env.send("app", "")  # approve
    st = wait_for(lambda: status(cfg).state == "done" and status(cfg), what="done")
    assert st.message == "Codex did: fix the tests"

    env.send("app", "another one")
    wait_for(lambda: status(cfg).state == "waiting", what="second approval")
    env.send("app", "esc")  # interrupt
    st = wait_for(lambda: status(cfg).state == "idle" and status(cfg), what="interrupted")
    assert st.message == "interrupted"


@needs_tmux
async def test_codex_resume_picker_and_c(env, capsys):
    cfg = codex_config(env)
    cli.main(["setup"])

    def talk(prompt):
        n = len(runs(env))
        cli.main(["start", "app", "-d"])
        wait_for(lambda: len(runs(env)) > n, what="codex started")
        env.send("app", prompt)
        wait_for(lambda: status(cfg).state == "waiting", what="approval")
        env.send("app", "")
        wait_for(lambda: status(cfg).state == "done", what="done")
        conv = status(cfg).session_id
        cli.main(["stop", "app"])
        return conv

    first = talk("add a login page")
    second = talk("write the docs")
    capsys.readouterr()
    items = sessions.conversations(cfg, "app")
    assert [c.id for c in items] == [second, first]
    assert items[1].title == "Codex: add a login page"
    assert items[1].first == "add a login page"  # injected <environment_context> skipped

    # the conversation view reads Codex's rollout files and labels the replies "codex"
    from derot.tui import render_conversation
    conv = sessions.conversation(cfg, "app", status(cfg).transcript)
    assert [i["role"] for i in conv] == ["you", "claude"]
    assert "codex\nCodex did: write the docs" in render_conversation(conv, "codex").plain

    # c resumes this session's own conversation; R resumes the one you pick
    app = Derot(config.load())
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.pause(1)
        await pilot.press("c")
        for _ in range(50):
            await pilot.pause(0.1)
            if len(runs(env)) == 3:
                break
    assert runs(env)[-1]["args"] == ["resume", second]
    env.send("app", "one more thing")  # (Codex reports nothing before the first prompt)
    wait_for(lambda: status(cfg).session_id == second, what="the same conversation")
    cli.main(["stop", "app"])
    assert cli.main(["start", "app", "-d", "--resume", first]) == 0
    wait_for(lambda: len(runs(env)) == 4, what="resumed run")
    assert runs(env)[-1]["args"] == ["resume", first]


def test_silent_codex_is_idle_unless_its_hooks_need_approval(monkeypatch):
    """Real Codex 0.164 sends nothing (not even SessionStart) before the first prompt, so
    silence only means "needs you" when derot's hooks aren't approved in /hooks."""
    cfg = config.parse({"accounts": {"oa": {"agent": "codex"}},
                        "sessions": [{"name": "a", "dir": "/x", "account": "oa"}]})
    out = "@@TMUX\ncc-a|0|1000\n@@NOW\n1060\n@@STATE\n@@HOOK\nyes\n@@END\n"
    monkeypatch.setattr(installer, "CODEX_UNAPPROVED", set())
    st = sessions.resolve(cfg, cfg.sessions[0], sessions.parse_poll(out))
    assert st.state == "idle" and st.message == ""
    installer.CODEX_UNAPPROVED.add(("local", "~/.codex"))
    st = sessions.resolve(cfg, cfg.sessions[0], sessions.parse_poll(out))
    assert st.state == "waiting" and "/hooks" in st.message


def test_codex_hook_approval_is_read_from_config_toml(env, monkeypatch):
    cfg = codex_config(env)
    monkeypatch.setattr(installer, "CODEX_UNAPPROVED", set())
    assert installer.setup_host(cfg, cfg.hosts["local"], False, lambda line: None)
    host, home = cfg.hosts["local"], env.home / ".codex-work"
    assert installer.hooks_present(host, "~/.codex-work", "codex")
    assert ("local", "~/.codex-work") in installer.CODEX_UNAPPROVED
    # what Codex writes when you trust them in /hooks
    hooks_json = str(home / "hooks.json")
    (home / "config.toml").write_text("".join(
        f'[hooks.state."{hooks_json}:{event}:0:0"]\ntrusted_hash = "sha256:x"\n'
        for event in ("session_start", "user_prompt_submit", "pre_tool_use",
                      "permission_request", "post_tool_use", "stop", "interrupt",
                      "session_end")))
    assert installer.hooks_present(host, "~/.codex-work", "codex")
    assert ("local", "~/.codex-work") not in installer.CODEX_UNAPPROVED


def test_codex_start_and_login_commands(env, monkeypatch):
    cfg = codex_config(env)
    s = cfg.session("app")
    host = cfg.hosts["local"]
    assert sessions._codex_cmd(host, s, False, "", "").endswith("codex")
    assert sessions._codex_cmd(host, s, True, "", "").endswith("codex resume --last")
    assert sessions._codex_cmd(host, s, False, "id-1", "").endswith("codex resume id-1")
    fallback = sessions._codex_cmd(host, s, True, "id-1", "/t/r.jsonl")
    assert "then" in fallback and "resume id-1" in fallback and "resume --last" in fallback

    ran = []
    monkeypatch.setattr(remote, "interactive", lambda host, argv: ran.append(argv) or 0)
    sessions.login(cfg, "oa")
    script = (env.home / ".derot" / "run" / "_login.sh").read_text()
    assert f"{env.codex} login" in script and "CODEX_HOME" in script


async def test_account_form_adds_a_codex_account(env):
    env.write_config("accounts: {me: {config_dir: ~/.claude}}\nsessions: []\n")
    cfg = config.load()
    results = []
    app = Derot(cfg, poll_on_mount=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.push_screen(AccountForm(cfg), results.append)
        await pilot.pause()
        app.screen.query_one("#agent", Select).value = "codex"
        await pilot.pause()
        name = app.screen.query_one("#name", Input)
        name.focus()
        await pilot.press(*"work")
        assert app.screen.query_one("#config_dir", Input).value == "~/.codex-work"
        assert "codex login" in app.screen.query_one("#api_key", Input).placeholder
        key = app.screen.query_one("#api_key", Input)
        key.focus()
        await pilot.press(*"sk-test")
        await pilot.press("enter")
        await pilot.pause()
    acct = results[0]
    assert (acct.agent, acct.config_dir, acct.env) == ("codex", "~/.codex-work",
                                                         {"OPENAI_API_KEY": "sk-test"})
