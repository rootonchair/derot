"""Preview (conversation / screen) and reply-without-attaching (tracking 014, 015)."""

import json
import time

import pytest
from textual.widgets import DataTable, Static

from ccdeck import cli, config, sessions
from ccdeck.tui import CCDeck, render_conversation

from .conftest import needs_tmux


def write_transcript(path, entries):
    path.write_text("".join(json.dumps(e) + "\n" for e in entries))


def test_conversation_parses_real_transcript_shapes(env, tmp_path):
    env.write_config("sessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    t = tmp_path / "t.jsonl"
    write_transcript(t, [
        {"type": "user", "message": {"content": "<command-name>/clear</command-name>"}},
        {"type": "user", "message": {"content": "fix the login bug"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Looking."}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Bash", "input": {"command": "npm  test"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True,
            "content": "The user doesn't want to proceed with this tool use."}]}},
        {"type": "user", "message": {"content": [
            {"type": "text", "text": "[Request interrupted by user for tool use]"}]}},
        {"type": "assistant", "isSidechain": True,
         "message": {"content": [{"type": "text", "text": "subagent noise"}]}},
        {"type": "user", "isMeta": True, "message": {"content": "meta"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Fixed it."}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Anything else?"}]}},
        "not json",
    ])
    items = sessions.conversation(cfg, "a", str(t))
    assert items == [
        {"role": "you", "text": "fix the login bug"},
        {"role": "claude", "text": "Looking."},
        {"role": "tool", "text": "Bash: npm test"},
        {"role": "note", "text": "declined"},
        {"role": "note", "text": "interrupted"},
        {"role": "claude", "text": "Fixed it.\n\nAnything else?"},
    ]
    assert "you\nfix the login bug" in render_conversation(items).plain
    assert sessions.conversation(cfg, "a", "") == []
    assert sessions.conversation(cfg, "a", str(tmp_path / "missing.jsonl")) == []
    with pytest.raises(sessions.SessionError):  # unreadable is still an error
        sessions.conversation(cfg, "a", str(tmp_path))


async def wait_until(pilot, cond, what, tries=75):
    for _ in range(tries):
        await pilot.pause(0.2)
        if cond():
            return
    raise AssertionError(f"timed out waiting for {what}")


def preview_text(app):
    return str(app.query_one("#preview", Static).render())


@needs_tmux
async def test_preview_follows_a_session_driven_without_attaching(env, capsys):
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
sessions: [{{name: shop, dir: ~/shop}}]
""")
    (env.home / "shop").mkdir()
    cli.main(["setup"])
    cli.main(["start", "shop", "-d"])
    capsys.readouterr()
    app = CCDeck(config.load())

    def state():
        return {st.name: st for st in app.statuses}["shop"].state

    async with app.run_test(size=(150, 40)) as pilot:
        await wait_until(pilot, lambda: state() == "idle", "idle")
        await pilot.press("enter", *"build it", "enter", "ctrl+q")  # type, then stop
        await wait_until(pilot, lambda: state() == "waiting", "waiting")

        # needs you: the preview shows the live screen with the prompt
        await wait_until(pilot, lambda: "allow Bash?" in preview_text(app), "screen preview")
        assert app.query_one("#preview-box").border_title.startswith("screen (auto)")
        # the detached session was resized to the preview, so Claude lays out for it
        # (height can lag by a line while the header above the preview re-lays out)
        region = app.query_one("#preview-box").content_region
        size = env.tmux("display", "-p", "-t", "=cc-shop:", "#{window_width} #{window_height}")
        w, h = map(int, size.stdout.split())
        assert w == region.width and abs(h - region.height) <= 2

        await pilot.press("enter", "enter", "ctrl+q")  # type: accept the highlighted option
        await wait_until(pilot, lambda: state() == "done", "done")

        # done: still Claude's own screen, the same UI as typing live or attaching
        await wait_until(pilot, lambda: "All done with: build it" in preview_text(app),
                         "screen after reply")
        assert app.query_one("#preview-box").border_title.startswith("screen (auto)")
        assert "[fake-claude]" in preview_text(app)

        # p switches to the conversation from the transcript
        await pilot.press("p")
        assert app.preview_mode == "conversation"
        await wait_until(pilot, lambda: app.query_one("#preview-box").border_title
                         .startswith("conversation"), "conversation view")
        assert "you\nbuild it" in preview_text(app)
        assert "[fake-claude]" not in preview_text(app)


async def test_digits_go_to_waiting_session_only(env, monkeypatch):
    sent = []
    monkeypatch.setattr(sessions, "send_key", lambda cfg, name, key: sent.append((name, key)))
    monkeypatch.setattr(sessions, "screen", lambda cfg, name: sessions.Screen(""))
    monkeypatch.setattr(sessions, "fit", lambda *a: None)
    env.write_config("sessions: [{name: a, dir: /x}, {name: b, dir: /y}]\n")
    cfg = config.load()
    app = CCDeck(cfg, poll_on_mount=False)
    async with app.run_test(size=(150, 40)) as pilot:
        sts = [sessions.Status(s, cfg.host_of(s), cfg.account_of(s), state=st)
               for s, st in zip(cfg.sessions, ["waiting", "busy"])]
        app.apply_poll(sts, {})
        await pilot.pause()
        app.query_one(DataTable).move_cursor(row=0)  # a: waiting
        await pilot.press("1")
        await app.workers.wait_for_complete()
        assert sent == [("a", "1")]
        app.query_one(DataTable).move_cursor(row=1)  # b: busy — digits do nothing
        await pilot.press("2")
        await app.workers.wait_for_complete()
        assert sent == [("a", "1")]


async def test_missing_transcript_shows_screen_not_error(env, tmp_path, monkeypatch):
    """Claude only creates the transcript with the first message (seen on a real session)."""
    env.write_config("sessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    assert sessions.conversation(cfg, "a", str(tmp_path / "not-yet.jsonl")) == []
    monkeypatch.setattr(sessions, "screen", lambda cfg, name: sessions.Screen(
        "╭ Claude Code ╮ > \x1b[2mTry it\x1b[0m"))
    monkeypatch.setattr(sessions, "fit", lambda *a: None)
    app = CCDeck(cfg, poll_on_mount=False)
    async with app.run_test(size=(150, 40)) as pilot:
        s = cfg.sessions[0]
        app.apply_poll([sessions.Status(s, cfg.host_of(s), cfg.account_of(s), state="idle",
                                        transcript=str(tmp_path / "not-yet.jsonl"))], {})
        await wait_until(pilot, lambda: "Claude Code" in preview_text(app), "screen fallback")
        assert "couldn't" not in preview_text(app)
        # styles survive: the dim suggestion is rendered dim, not as raw escape codes
        assert "\x1b" not in preview_text(app)
        spans = app.query_one("#preview").render().spans
        assert any("dim" in str(sp.style) for sp in spans)
        assert app.query_one("#preview-box").border_title.startswith("screen (auto)")



def test_tmux_key_mapping():
    assert sessions.tmux_key("enter") == "Enter"
    assert sessions.tmux_key("shift+tab") == "BTab"
    assert sessions.tmux_key("ctrl+c") == "C-c"
    assert sessions.tmux_key("up") == "Up"
    assert sessions.tmux_key("f5") == "F5"
    assert sessions.tmux_key("ctrl+shift+weird") is None
    # newline in Claude's prompt, word motion, undo: these used to be dropped
    assert sessions.tmux_key("shift+enter") == sessions.tmux_key("alt+enter") == "M-Enter"
    assert sessions.tmux_key("ctrl+left") == "C-Left"
    assert sessions.tmux_key("ctrl+underscore") == "C-_"
    assert sessions.tmux_key("alt+backspace") == "M-BSpace"
    assert sessions.tmux_key("ctrl+f5") == "C-F5"


def test_render_screen_draws_cursor():
    from ccdeck.tui import render_screen
    t = render_screen(sessions.Screen("ab\n> /mo", (80, 24), (5, 1)), cursor=True)
    assert t.plain == "ab\n> /mo "  # cursor after the text gets a cell
    assert any("reverse" in str(sp.style) and sp.start == 8 for sp in t.spans)
    assert render_screen(sessions.Screen("x", (80, 24), (0, 0)), cursor=False).spans == []


@needs_tmux
async def test_live_typing_reaches_claude_key_by_key(env, capsys):
    """Typing live: keys go to the session one by one (so Claude's own menus and
    suggestions work), app keys like q/x/d don't fire, Ctrl-q stops."""
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
sessions: [{{name: shop, dir: ~/shop}}]
""")
    (env.home / "shop").mkdir()
    cli.main(["setup"])
    cli.main(["start", "shop", "-d"])
    capsys.readouterr()
    app = CCDeck(config.load())

    def status():
        return {st.name: st for st in app.statuses}["shop"]

    async with app.run_test(size=(150, 40)) as pilot:
        await wait_until(pilot, lambda: status().state == "idle", "idle")
        await pilot.press("enter")  # type into it
        assert app.live == "shop"
        assert app.query_one("#preview-box").border_title.startswith("typing into shop")
        # q, x, d, e, n would quit/stop/remove/edit/new on the list: here they're just text
        await pilot.press(*"quick fix and exit", "backspace", "t", "enter")
        await wait_until(pilot, lambda: status().state == "waiting", "prompt received")
        assert status().prompt == "quick fix and exit"
        assert app.is_running
        await pilot.press("enter")  # Enter in live mode reaches Claude (approve), not attach
        await wait_until(pilot, lambda: status().state == "done", "done")
        await pilot.press("ctrl+q")  # stops typing, doesn't quit
        await pilot.pause()
        assert app.live is None and app.is_running
        assert isinstance(app.focused, DataTable)


async def test_preview_follows_the_cursor_without_showing_a_stale_session(env, monkeypatch):
    """Moving down the list while a preview is loading used to leave the old session's
    screen under the new session's header until the next 2 s refresh."""
    def slow_screen(cfg, name):
        time.sleep(0.8 if name == "a" else 0)
        return sessions.Screen(f"screen of {name}")
    monkeypatch.setattr(sessions, "screen", slow_screen)
    monkeypatch.setattr(sessions, "fit", lambda *a: None)
    env.write_config("sessions: [{name: a, dir: /x}, {name: b, dir: /y}]\n")
    cfg = config.load()
    app = CCDeck(cfg, poll_on_mount=False)
    async with app.run_test(size=(150, 40)) as pilot:
        app.apply_poll([sessions.Status(s, cfg.host_of(s), cfg.account_of(s), state="idle")
                        for s in cfg.sessions], {})
        table = app.query_one(DataTable)
        table.move_cursor(row=0)
        app.refresh_preview()
        await pilot.pause(0.1)  # a's preview is loading
        table.move_cursor(row=1)
        await pilot.pause()
        assert "screen of a" not in preview_text(app)  # never a's screen under b's header
        await wait_until(pilot, lambda: "screen of b" in preview_text(app), "b's preview",
                         tries=6)  # well before the 2 s refresh tick


async def test_click_on_the_right_panel_starts_typing(env, monkeypatch):
    monkeypatch.setattr(sessions, "screen", lambda cfg, name: sessions.Screen(f"screen {name}"))
    monkeypatch.setattr(sessions, "fit", lambda *a: None)
    env.write_config("sessions: [{name: a, dir: /x}, {name: b, dir: /y}]\n")
    cfg = config.load()
    app = CCDeck(cfg, poll_on_mount=False)
    async with app.run_test(size=(150, 40)) as pilot:
        app.apply_poll([sessions.Status(s, cfg.host_of(s), cfg.account_of(s), state=st)
                        for s, st in zip(cfg.sessions, ["idle", "stopped"])], {})
        app.query_one(DataTable).move_cursor(row=0)
        await pilot.pause()
        await pilot.click("#preview-box")
        assert app.live == "a"
        assert app.query_one("#preview-box").border_title.startswith("typing into a")
        await pilot.press("ctrl+q")
        await pilot.pause()
        assert app.live is None

        await pilot.click("#detail")  # the details above the preview count too
        assert app.live == "a"
        await pilot.press("ctrl+q")

        app.query_one(DataTable).move_cursor(row=1)  # stopped: a hint, no typing
        await pilot.pause()
        await pilot.click("#preview-box")
        assert app.live is None

        app.query_one(DataTable).move_cursor(row=0)
        await pilot.pause()
        region = app.query_one("#preview-box").region
        from ccdeck.forms import Confirm
        app.push_screen(Confirm("sure?"))
        await pilot.pause()
        await pilot.click(offset=(region.x + 2, region.bottom - 2))  # behind a form: nothing
        assert app.live is None
