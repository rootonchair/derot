"""Resuming a past conversation (tracking 012): listing, the R picker, and `c`."""

import json

from textual.widgets import OptionList

from ccdeck import cli, config, sessions
from ccdeck.forms import ResumePicker
from ccdeck.tui import CCDeck

from .conftest import needs_tmux, wait_for


def setup_shop(env, capsys):
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
sessions: [{{name: shop, dir: ~/shop}}]
""")
    (env.home / "shop").mkdir()
    cli.main(["setup"])
    capsys.readouterr()
    return config.load()


def runs(env):
    log = env.home / ".claude" / "fake-claude-runs.log"
    return [json.loads(ln) for ln in log.read_text().splitlines()] if log.exists() else []


def state_of(cfg, name="shop"):
    return {st.name: st for st in sessions.poll(cfg)}[name]


def talk(env, cfg, prompt):
    """Start shop fresh, have one exchange, stop it."""
    cli.main(["start", "shop", "-d"])
    wait_for(lambda: state_of(cfg).session_id, what="SessionStart")
    env.send("shop", prompt)
    wait_for(lambda: state_of(cfg).state == "waiting", what="prompt")
    env.send("shop", "")
    wait_for(lambda: state_of(cfg).state == "done", what="done")
    conv = state_of(cfg).session_id
    cli.main(["stop", "shop"])
    return conv


@needs_tmux
def test_lists_past_conversations_and_resumes_one(env, capsys):
    cfg = setup_shop(env, capsys)
    first = talk(env, cfg, "fix the login bug")
    second = talk(env, cfg, "add dark mode")
    capsys.readouterr()

    items = sessions.conversations(cfg, "shop")
    assert [c.id for c in items] == [second, first]  # newest first
    assert items[1].title == "About fix the login bug"
    assert items[1].first == items[1].last == "fix the login bug"

    assert cli.main(["history", "shop"]) == 0
    out = capsys.readouterr().out
    assert first in out and "About add dark mode" in out

    assert cli.main(["start", "shop", "-d", "--resume", first]) == 0
    wait_for(lambda: len(runs(env)) == 3, what="resumed run")
    assert runs(env)[-1]["args"] == ["--resume", first]
    wait_for(lambda: state_of(cfg).session_id == first, what="resumed conversation")


@needs_tmux
async def test_picker_and_c_resume_this_sessions_conversation(env, capsys):
    cfg = setup_shop(env, capsys)
    first = talk(env, cfg, "fix the login bug")
    talk(env, cfg, "add dark mode")
    capsys.readouterr()

    app = CCDeck(config.load())
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.pause(1)
        await pilot.press("R")
        await pilot.pause()
        assert isinstance(app.screen, ResumePicker)
        lst = app.screen.query_one("#conversations", OptionList)
        for _ in range(50):
            await pilot.pause(0.1)
            if lst.option_count:
                break
        assert lst.option_count == 2
        assert lst.highlighted == 0  # the last one used here, marked
        assert "last used here" in str(lst.get_option_at_index(0).prompt)
        await pilot.press("down", "enter")  # the older one
        for _ in range(50):
            await pilot.pause(0.1)
            if len(runs(env)) == 3:
                break
        assert runs(env)[-1]["args"] == ["--resume", first]
        assert not isinstance(app.screen, ResumePicker)
    wait_for(lambda: state_of(cfg).session_id == first, what="resumed")
    cli.main(["stop", "shop"])

    # a newer conversation in the same folder, started outside ccdeck: --continue would
    # pick it, but c resumes the one this session last used
    project = next((env.home / ".claude" / "projects").iterdir())
    (project / "outside.jsonl").write_text(
        json.dumps({"type": "user", "message": {"content": "started elsewhere"}}) + "\n")
    assert sessions.conversations(cfg, "shop")[0].id == "outside"

    app = CCDeck(config.load())
    async with app.run_test(size=(150, 40)) as pilot:
        await pilot.pause(1)
        await pilot.press("c")
        for _ in range(50):
            await pilot.pause(0.1)
            if len(runs(env)) == 4:
                break
    assert runs(env)[-1]["args"] == ["--resume", first]  # c: this session's own


@needs_tmux
def test_c_falls_back_to_continue_when_nothing_was_said(env, capsys):
    cfg = setup_shop(env, capsys)
    cli.main(["start", "shop", "-d"])
    wait_for(lambda: state_of(cfg).session_id, what="SessionStart")
    st = state_of(cfg)
    assert st.session_id  # known from SessionStart, but no transcript yet
    cli.main(["stop", "shop"])
    sessions.start(cfg, "shop", True, resume=st.session_id, resume_file=st.transcript)
    wait_for(lambda: len(runs(env)) == 2, what="second run")
    assert runs(env)[-1]["args"] == ["--continue"]


def test_picker_handles_no_conversations(env, monkeypatch):
    monkeypatch.setattr(sessions, "conversations", lambda cfg, name, limit=40: [])
    env.write_config("sessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    results = []
    app = CCDeck(cfg, poll_on_mount=False)

    async def run():
        async with app.run_test(size=(150, 40)) as pilot:
            app.push_screen(ResumePicker(cfg, "a"), results.append)
            await pilot.pause(0.3)
            assert "No past conversations" in str(app.screen.query_one("#picker-status")
                                                  .render())
            await pilot.press("escape")
            await pilot.pause()

    import asyncio
    asyncio.run(run())
    assert results == [None]


def test_late_session_end_of_a_stopped_session_does_not_claim_the_new_one():
    """Stop then start quickly: start deletes the state file, then the old (killed) Claude's
    SessionEnd arrives. It used to claim the file, so the new session was ignored."""
    from ccdeck import hook
    state = {}
    assert not hook.owns(state, "SessionEnd", {"session_id": "old"})
    assert hook.owns(state, "SessionStart", {"session_id": "new"})
    state = {"session_id": "new"}
    assert hook.owns(state, "UserPromptSubmit", {"session_id": "new"})
    assert not hook.owns(state, "SessionEnd", {"session_id": "old"})
    assert hook.owns({}, "UserPromptSubmit", {"session_id": "x"})  # hooks set up mid-session

