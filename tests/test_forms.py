import yaml
from textual.widgets import DataTable, Input, Static

from ccdeck import config
from ccdeck.config import Account, Host
from ccdeck.forms import AccountForm, HostForm, SessionForm, slug
from ccdeck.tui import CCDeck


def start_cfg(env, text="accounts: {personal: {config_dir: ~/.claude}}\nsessions: []\n"):
    env.write_config(text)
    return config.load()


async def type_into(pilot, wid, text):
    inp = pilot.app.screen.query_one(f"#{wid}", Input)
    inp.focus()
    inp.value = ""
    await pilot.press(*list(text))


def test_slug():
    assert slug("My Project!") == "My-Project"
    assert slug("...") == ""


def test_save_round_trip_keeps_backup(env):
    env.write_config("# my comment\nhosts: {vm: {ssh: me@vm}}\nsessions: [{name: a, dir: ~/a}]\n")
    cfg = config.load()
    cfg.sessions[0].note = "hello"
    config.save(cfg)
    again = config.load()
    assert again.sessions[0].note == "hello" and again.hosts["vm"].ssh == "me@vm"
    assert "# my comment" in env.config.with_name("config.yaml.bak").read_text()
    data = yaml.safe_load(env.config.read_text())
    assert data["sessions"] == [{"name": "a", "host": "local", "dir": "~/a",
                                 "account": "default", "note": "hello"}]


async def test_add_edit_remove_session_from_ui(env):
    (env.home / "code" / "shop-api").mkdir(parents=True)
    app = CCDeck(start_cfg(env), poll_on_mount=False)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        assert isinstance(app.screen, SessionForm)
        await type_into(pilot, "dir", "~/code/shop-api")
        assert app.screen.query_one("#name", Input).value == "shop-api"  # auto-filled
        await type_into(pilot, "note", "payments")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert not isinstance(app.screen, SessionForm)
        saved = config.load()
        assert [(s.name, s.dir, s.account, s.note) for s in saved.sessions] == [
            ("shop-api", "~/code/shop-api", "personal", "payments")]
        assert app.query_one(DataTable).row_count == 1

        # edit
        await pilot.press("e")
        await pilot.pause()
        assert app.screen.query_one("#dir", Input).value == "~/code/shop-api"
        await type_into(pilot, "note", "refunds")
        await pilot.press("enter")
        await pilot.pause()
        assert config.load().sessions[0].note == "refunds"

        # remove (confirm with y): its files on the host go too (tracking 010)
        state = env.home / ".ccdeck" / "state" / "shop-api.json"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text('{"state": "done", "message": "old result"}')
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert config.load().sessions == []
        assert app.query_one("#empty").display
        await app.workers.wait_for_complete()
        assert not state.exists()


async def test_session_form_validates(env):
    app = CCDeck(start_cfg(env), poll_on_mount=False)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        await type_into(pilot, "dir", "~/does-not-exist")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(app.screen, SessionForm)
        assert "Folder not found" in str(app.screen.query_one("#error", Static).render())
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, SessionForm)
        assert config.load().sessions == []

        # $HOME/... is accepted and saved as ~/...
        (env.home / "proj").mkdir()
        await pilot.press("n")
        await pilot.pause()
        await type_into(pilot, "dir", "$HOME/proj")
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert not isinstance(app.screen, SessionForm)
        assert [s.dir for s in config.load().sessions] == ["~/proj"]


async def test_new_host_and_account_inline(env):
    app = CCDeck(start_cfg(env), poll_on_mount=False)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        form = app.screen
        form._host_added(Host("vm", "me@vm"))
        form._account_added(Account("work", "~/.claude-work", {"ANTHROPIC_API_KEY": "k"}))
        await type_into(pilot, "dir", "~/remote/api")  # remote dirs aren't checked locally
        await pilot.press("ctrl+s")
        await pilot.pause()
        saved = config.load()
        assert saved.hosts["vm"].ssh == "me@vm"
        assert saved.accounts["work"].env == {"ANTHROPIC_API_KEY": "k"}
        assert (saved.sessions[0].host, saved.sessions[0].account) == ("vm", "work")
        await app.workers.wait_for_complete()  # hook install on the fake VM


async def test_account_and_host_forms(env):
    cfg = start_cfg(env)
    results = []
    app = CCDeck(cfg, poll_on_mount=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.push_screen(AccountForm(cfg), results.append)
        await pilot.pause()
        await type_into(pilot, "name", "work")
        assert app.screen.query_one("#config_dir", Input).value == "~/.claude-work"
        await pilot.press("enter")
        await pilot.pause()
        app.push_screen(HostForm(cfg), results.append)
        await pilot.pause()
        await type_into(pilot, "ssh", "me@build-box.example.com")
        assert app.screen.query_one("#name", Input).value == "build-box"
        await pilot.press("enter")
        await pilot.pause()
    assert results[0] == Account("work", "~/.claude-work", {})
    assert results[1] == Host("build-box", "me@build-box.example.com", "claude")


def write_ssh(home):
    ssh = home / ".ssh"
    (ssh / "conf.d").mkdir(parents=True)
    (ssh / "config").write_text(
        "Host *\n  ServerAliveInterval 30\n"
        "Host prod-api prod-db  # two aliases\n  HostName 10.0.0.5\n  User deploy\n"
        "Include conf.d/*\n"
        "Host = staging\n  HostName=stage.example.com\n")
    (ssh / "conf.d" / "gpu").write_text("Host gpu-box\n  HostName gpu.lab\n")
    (ssh / "known_hosts").write_text(
        "github.com,140.82.1.1 ssh-ed25519 AAAA\n"
        "[build.lab]:2222 ssh-ed25519 AAAA\n"
        "|1|hashed= ssh-ed25519 AAAA\n"
        "prod-api ssh-ed25519 AAAA\n")


def test_ssh_targets_from_config_and_known_hosts(env):
    from ccdeck.forms import match_targets, ssh_targets
    write_ssh(env.home)
    targets = ssh_targets()
    assert targets == [
        ("prod-api", "deploy@10.0.0.5"), ("prod-db", "deploy@10.0.0.5"),
        ("gpu-box", "gpu.lab"), ("staging", "stage.example.com"),
        ("github.com", "known host"), ("140.82.1.1", "known host"),
        ("build.lab", "known host"),
    ]
    assert [t for t, _ in match_targets("pro", targets)] == ["prod-api", "prod-db"]
    assert [t for t, _ in match_targets("me@gpu", targets)] == ["me@gpu-box"]
    assert [t for t, _ in match_targets("lab", targets)] == ["build.lab"]  # inside the name
    assert match_targets("staging", targets) == []  # typed in full: nothing to show
    assert ssh_targets(str(env.root / "nobody")) == []


async def test_host_form_lists_matching_targets(env):
    write_ssh(env.home)
    cfg = start_cfg(env)
    results = []
    app = CCDeck(cfg, poll_on_mount=False)
    async with app.run_test(size=(140, 40)) as pilot:
        app.push_screen(HostForm(cfg), results.append)
        await pilot.pause()
        await type_into(pilot, "ssh", "prod")
        await pilot.pause()
        lst = app.screen.query_one("#ssh-matches")
        assert lst.display and lst.option_count == 2
        await pilot.press("down", "enter")  # pick the second, don't save yet
        await pilot.pause()
        assert app.screen.query_one("#ssh", Input).value == "prod-db"
        assert not lst.has_class("shown") and isinstance(app.screen, HostForm)
        assert app.screen.query_one("#name", Input).value == "prod-db"
        await type_into(pilot, "ssh", "gp")
        await pilot.press("escape")  # closes the list, not the form
        await pilot.pause()
        assert isinstance(app.screen, HostForm) and not lst.has_class("shown")
        await pilot.press("enter")  # list closed: Enter saves as typed
        await pilot.pause()
    assert results == [Host("gp", "gp", "claude")]


async def test_folder_suggestions_on_an_ssh_machine(env):
    from ccdeck.forms import PathSuggester
    (env.vm_home() / "code" / "shop-api").mkdir(parents=True)
    (env.vm_home() / "code" / ".hidden").mkdir()
    (env.vm_home() / "code" / "notes.txt").write_text("")
    (env.home / "code" / "local-only").mkdir(parents=True)
    vm = PathSuggester(Host("vm", "me@vm"))
    assert await vm.get_suggestion("~/co") == "~/code"
    assert await vm.get_suggestion("~/code/sh") == "~/code/shop-api"
    assert await vm.get_suggestion("~/code/no") is None  # files aren't folders
    assert await vm.get_suggestion("~/code/.h") == "~/code/.hidden"
    assert await vm.get_suggestion("$HOME/code/sh") == "$HOME/code/shop-api"
    assert await vm.get_suggestion("~/code/lo") is None  # the VM's folders, not this Mac's
    assert await vm.get_suggestion("~/missing/x") is None
    assert await PathSuggester().get_suggestion("~/code/lo") == "~/code/local-only"
    assert await PathSuggester(Host("deadvm", "me@deadvm")).get_suggestion("~/co") is None


async def test_session_form_lists_folders_of_the_chosen_machine(env):
    from textual.widgets import Select
    (env.vm_home() / "code" / "shop-api").mkdir(parents=True)
    (env.vm_home() / "code" / "shop-web").mkdir()
    (env.home / "code" / "local-only").mkdir(parents=True)
    cfg = start_cfg(env, "hosts: {vm: {ssh: me@vm}}\n"
                         "accounts: {personal: {config_dir: ~/.claude}}\nsessions: []\n")
    app = CCDeck(cfg, poll_on_mount=False)

    async def shown(pilot):
        lst = app.screen.query_one("#dir-matches")
        for _ in range(40):  # remote listings run in a worker
            await pilot.pause(0.05)
            if lst.has_class("shown"):
                break
        return [str(lst.get_option_at_index(i).id) for i in range(lst.option_count)] \
            if lst.has_class("shown") else []

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("n")
        await pilot.pause()
        await type_into(pilot, "dir", "~/code/lo")  # this Mac
        assert await shown(pilot) == ["~/code/local-only/"]

        app.screen.query_one("#host", Select).value = "vm"
        await pilot.pause()
        await type_into(pilot, "dir", "~/co")
        assert await shown(pilot) == ["~/code/"]
        await pilot.press("enter")  # picks (doesn't save) and keeps the list closed
        await pilot.pause()
        assert app.screen.query_one("#dir", Input).value == "~/code/"
        assert await shown(pilot) == []
        await pilot.press("s")  # typing on lists what's inside
        assert await shown(pilot) == ["~/code/shop-api/", "~/code/shop-web/"]
        await pilot.press("down", "tab")
        await pilot.pause()
        assert app.screen.query_one("#dir", Input).value == "~/code/shop-web/"
        assert app.screen.query_one("#name", Input).value == "shop-web"
        await pilot.press("enter")  # list closed: Enter saves
        await pilot.pause()
        saved = config.load()
        assert [(x.name, x.host, x.dir) for x in saved.sessions] == [
            ("shop-web", "vm", "~/code/shop-web")]
        await app.workers.wait_for_complete()
