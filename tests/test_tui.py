import time

import yaml
from textual.widgets import DataTable, Static

from derot import config, notify
from derot.sessions import Status
from derot.tui import Derot

CFG = """
hosts: {vm: {ssh: me@vm}}
accounts: {personal: {}, work: {config_dir: ~/.claude-work}}
sessions:
  - {name: alpha, host: local, dir: ~/a, account: personal, note: the note}
  - {name: beta, host: vm, dir: ~/b, account: work}
  - {name: gamma, host: local, dir: ~/c, account: work}
"""


def make_cfg():
    return config.parse(yaml.safe_load(CFG))


def statuses(cfg, states, messages=None):
    out = []
    for s in cfg.sessions:
        st = Status(s, cfg.host_of(s), cfg.account_of(s), state=states[s.name],
                    ts=time.time() - 5, message=(messages or {}).get(s.name, ""))
        out.append(st)
    from derot.sessions import sort_key
    return sorted(out, key=sort_key)


def row_names(app):
    table = app.query_one(DataTable)
    return [table.coordinate_to_cell_key((i, 0)).row_key.value for i in range(table.row_count)]


async def test_renders_rows_keeps_cursor_and_notifies_once(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda t, b, s="": sent.append((t, b)))
    cfg = make_cfg()
    app = Derot(cfg, poll_on_mount=False)
    async with app.run_test(size=(140, 30)) as pilot:
        app.apply_poll(statuses(cfg, {"alpha": "idle", "beta": "busy", "gamma": "stopped"}), {})
        await pilot.pause()
        assert row_names(app) == ["beta", "alpha", "gamma"]
        assert "1 working" in str(app.query_one("#summary", Static).render())

        table = app.query_one(DataTable)
        table.move_cursor(row=row_names(app).index("gamma"))
        await pilot.pause()
        assert app.selected_name() == "gamma"
        assert "c: continue last conversation" in str(app.query_one("#detail", Static).render())

        # gamma stays selected though the order changes; beta → waiting notifies once
        app.apply_poll(statuses(cfg, {"alpha": "idle", "beta": "waiting", "gamma": "stopped"},
                                {"beta": "Claude needs your permission to use Bash"}), {})
        await pilot.pause()
        assert app.selected_name() == "gamma"
        assert sent == [("beta needs you", "Claude needs your permission to use Bash")]

        app.apply_poll(statuses(cfg, {"alpha": "done", "beta": "waiting", "gamma": "stopped"},
                                {"alpha": "All done", "beta": "x"}), {})
        await pilot.pause()
        assert row_names(app) == ["beta", "alpha", "gamma"]
        assert app.selected_name() == "gamma"
        assert sent[1:] == [("alpha finished", "All done")]

        # same states again: no new alerts
        app.apply_poll(statuses(cfg, {"alpha": "done", "beta": "waiting", "gamma": "stopped"}), {})
        await pilot.pause()
        assert len(sent) == 2


async def test_first_poll_does_not_alert_and_offline_summary(monkeypatch):
    sent = []
    monkeypatch.setattr(notify, "send", lambda *a: sent.append(a))
    cfg = make_cfg()
    app = Derot(cfg, poll_on_mount=False)
    async with app.run_test(size=(140, 30)) as pilot:
        app.apply_poll(statuses(cfg, {"alpha": "waiting", "beta": "offline", "gamma": "done"}),
                       {"vm": "Connection refused"})
        await pilot.pause()
        assert sent == []
        summary = str(app.query_one("#summary", Static).render())
        assert "can't reach: vm" in summary and "1 need you" in summary


async def test_stop_needs_double_press(env, monkeypatch):
    cfg = make_cfg()
    app = Derot(cfg, poll_on_mount=False)
    stopped = []
    monkeypatch.setattr("derot.sessions.stop", lambda c, n: stopped.append(n))
    async with app.run_test(size=(140, 30)) as pilot:
        app.apply_poll(statuses(cfg, {"alpha": "busy", "beta": "idle", "gamma": "stopped"}), {})
        await pilot.pause()
        app.query_one(DataTable).move_cursor(row=0)  # alpha (busy)
        await pilot.press("x")
        await pilot.pause()
        assert stopped == []
        await pilot.press("x")
        await app.workers.wait_for_complete()
        assert stopped == ["alpha"]


async def test_empty_state():
    cfg = config.parse({})
    app = Derot(cfg, poll_on_mount=False)
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        empty = app.query_one("#empty", Static)
        assert empty.display and "press n to add one" in str(empty.render())


async def test_real_poll_against_tmux(env):
    import shutil
    import pytest
    from derot import cli
    if not shutil.which("tmux"):
        pytest.skip("tmux not installed")
    env.write_config(f"""
hosts: {{local: {{claude: "{env.claude}"}}}}
sessions:
  - {{name: shop, dir: ~/shop}}
  - {{name: idle-one, dir: ~/shop}}
""")
    (env.home / "shop").mkdir()
    cli.main(["setup"])
    cli.main(["start", "shop", "-d"])
    app = Derot(config.load())
    async with app.run_test(size=(140, 30)) as pilot:
        for _ in range(50):
            await pilot.pause(0.2)
            states = {st.name: st.state for st in app.statuses}
            if states == {"shop": "idle", "idle-one": "stopped"} and app.updated:
                break
        assert {st.name: st.state for st in app.statuses} == {"shop": "idle", "idle-one": "stopped"}
        assert row_names(app) == ["shop", "idle-one"]


async def test_s_c_start_in_background_enter_types_f_goes_full_screen(env, monkeypatch):
    from derot import sessions
    started, attached = [], []
    monkeypatch.setattr(sessions, "start", lambda cfg, name, cont=False, *a: started.append(
        (name, cont)))
    monkeypatch.setattr(Derot, "attach", lambda self, name: attached.append(name))
    monkeypatch.setattr(sessions, "screen", lambda cfg, name: sessions.Screen("screen"))
    monkeypatch.setattr(sessions, "fit", lambda *a: None)
    env.write_config("sessions: [{name: a, dir: /x}]\n")
    cfg = config.load()
    app = Derot(cfg, poll_on_mount=False)
    app.action_refresh = lambda: None
    async with app.run_test(size=(150, 40)) as pilot:
        stopped = [Status(s, cfg.host_of(s), cfg.account_of(s)) for s in cfg.sessions]
        app.apply_poll(stopped, {})
        await pilot.pause()
        await pilot.press("c")
        await app.workers.wait_for_complete()
        await pilot.press("s")
        await app.workers.wait_for_complete()
        assert started == [("a", True), ("a", False)] and attached == []  # stayed here
        assert app.live is None

        await pilot.press("enter")  # stopped: start it, then type into it
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert started[-1] == ("a", False) and app.live == "a" and attached == []
        await pilot.press("ctrl+q")
        await pilot.pause()
        await pilot.press("enter")  # running: just type
        await pilot.pause()
        assert app.live == "a" and len(started) == 3
        await pilot.press("ctrl+q")
        await pilot.pause()

        await pilot.press("f")  # full screen
        await pilot.pause()
        assert attached == ["a"]
        app.apply_poll([Status(s, cfg.host_of(s), cfg.account_of(s)) for s in cfg.sessions], {})
        await pilot.pause()
        await pilot.press("f")  # stopped: start, then full screen
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert len(started) == 4 and attached == ["a", "a"]


async def test_clicking_a_row_selects_it_and_never_attaches(env, monkeypatch):
    from derot import sessions
    attached = []
    monkeypatch.setattr(Derot, "attach", lambda self, name: attached.append(name))
    monkeypatch.setattr(sessions, "screen", lambda cfg, name: sessions.Screen("screen"))
    monkeypatch.setattr(sessions, "fit", lambda *a: None)
    env.write_config("sessions: [{name: a, dir: /x}, {name: b, dir: /y}]\n")
    cfg = config.load()
    app = Derot(cfg, poll_on_mount=False)
    app.action_refresh = lambda: None
    async with app.run_test(size=(150, 40)) as pilot:
        app.apply_poll([Status(s, cfg.host_of(s), cfg.account_of(s), state="idle")
                        for s in cfg.sessions], {})
        await pilot.pause()
        table = app.query_one(DataTable)
        table.move_cursor(row=0)
        await pilot.pause()
        region = table.region
        for _ in range(3):  # clicking the already selected row used to attach full screen
            await pilot.click(offset=(region.x + 6, region.y + 1))
            await pilot.pause()
        await pilot.click(offset=(region.x + 6, region.y + 2))  # another row: selects it
        await pilot.pause()
        assert attached == [] and app.selected_name() == "b"
        await pilot.press("f")
        await pilot.pause()
        assert attached == ["b"]
