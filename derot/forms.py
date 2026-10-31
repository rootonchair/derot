"""Form screens for changing the config from the console (no YAML editing needed)."""

from __future__ import annotations

import asyncio
import copy
import glob
import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import Button, Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from . import remote, sessions
from .config import (AGENTS, NAME_RE, Account, Config, ConfigError, Host, SessionDef,
                     norm_path, parse, to_dict)
from .log import log

ADD_HOST = "\0add-host"
ADD_ACCOUNT = "\0add-account"

FORM_CSS = """
ModalScreen { align: center middle; }
.form { width: 76; max-width: 100%; height: auto; max-height: 100%; padding: 0 2;
        border: round $accent; background: $surface; overflow-y: auto; }
.form .title { text-style: bold; margin: 1 0 0 0; }
.form Label { margin-top: 1; color: $text-muted; }
.form .hint { color: $text-muted; text-style: italic; }
.form .error { color: $error; margin-top: 1; height: auto; }
.form .buttons { height: 1; margin: 1 0; align-horizontal: right; }
.form .buttons Button { margin-left: 1; }
.form .matches { display: none; height: auto; max-height: 8; border: none;
                 background: $boost; padding: 0 1; }
.form .matches.shown { display: block; }
.form.picker { width: 110; }
.form.picker OptionList { height: auto; max-height: 24; border: none; background: $boost;
                          margin-top: 1; }
"""


def slug(text: str) -> str:
    """Turn a folder name into a valid session name."""
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", text.strip()).strip("-.")
    return s or ""


class PathSuggester(Suggester):
    """Completes folder paths (accept with →): on this machine, or over SSH on `host`
    (one listing per folder, cached briefly, run off the UI thread)."""

    CACHE_SECS = 30

    def __init__(self, host: Optional[Host] = None) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self.host = host if host and not host.is_local else None
        self._listings: dict = {}  # parent -> (time, folder names)

    def _local_dirs(self, parent: str) -> List[str]:
        return [e.name for e in os.scandir(os.path.expanduser(parent) or ".") if e.is_dir()]

    def _remote_dirs(self, parent: str) -> List[str]:
        # relative paths are relative to the home folder, like ssh itself
        cd = f"cd {remote.qpath(parent)} 2>/dev/null || exit 0; " if parent else ""
        proc = remote.sh(self.host, cd + 'for d in * .*; do [ -d "$d" ] && '
                         'printf "%s\\n" "$d"; done; true', timeout=8)
        if proc.returncode != 0:
            log.info("couldn't list %s on %s: %s", parent or "~", self.host.name,
                     remote.error_text(proc))
            return []
        return [n for n in proc.stdout.splitlines() if n not in (".", "..")]

    async def dirs(self, parent: str) -> List[str]:
        if self.host is None:
            return self._local_dirs(parent)
        cached = self._listings.get(parent)
        if cached and time.monotonic() - cached[0] < self.CACHE_SECS:
            return cached[1]
        names = await asyncio.to_thread(self._remote_dirs, parent)
        self._listings[parent] = (time.monotonic(), names)
        return names

    async def get_suggestion(self, value: str) -> Optional[str]:
        if not value:
            return None
        parent, prefix = os.path.split(norm_path(value))
        if value.startswith("~") and parent == "" and prefix == "~":
            return None
        try:
            found = await self.dirs(parent)
        except OSError:
            return None
        names = sorted(n for n in found if n.startswith(prefix)
                       and (prefix.startswith(".") or not n.startswith(".")))
        if not names or (len(names) == 1 and names[0] == prefix):
            return None
        return value + names[0][len(prefix):]


def ssh_targets(home: Optional[str] = None) -> List[Tuple[str, str]]:
    """SSH targets you've used: Host aliases from ~/.ssh/config (and its Includes) first,
    then hosts from ~/.ssh/known_hosts. Returns (target, detail) pairs, no duplicates."""
    ssh_dir = os.path.join(home or os.path.expanduser("~"), ".ssh")
    found: dict = {}  # target -> detail, in order

    def read_config(path: str, depth: int = 0) -> None:
        try:
            lines = Path(path).read_text(errors="replace").splitlines()
        except OSError:
            return
        current: List[str] = []
        info: dict = {}
        for raw in lines:
            line = raw.split("#", 1)[0].strip()
            m = re.match(r"(\S+?)\s*(?:=|\s)\s*(.+)", line)
            if not m:
                continue
            key, value = m.group(1).lower(), m.group(2).strip()
            if key == "include" and depth < 5:
                for pattern in value.split():
                    pattern = os.path.expanduser(pattern)
                    if not os.path.isabs(pattern):
                        pattern = os.path.join(ssh_dir, pattern)
                    for inc in sorted(glob.glob(pattern)):
                        read_config(inc, depth + 1)
            elif key == "host":
                current = [h for h in value.split() if not re.search(r"[*?!]", h)]
                info = {}
                for h in current:
                    found.setdefault(h, "")
            elif key == "match":
                current = []
            elif key in ("hostname", "user") and current:
                info[key] = value
                detail = info.get("hostname", "")
                if info.get("user"):
                    detail = f"{info['user']}@{detail or current[0]}"
                for h in current:
                    found[h] = detail

    read_config(os.path.join(ssh_dir, "config"))
    try:
        known = Path(ssh_dir, "known_hosts").read_text(errors="replace").splitlines()
    except OSError:
        known = []
    for line in known:
        parts = line.split()
        if not parts or line.startswith(("#", "|", "@")):  # hashed / markers: no name
            continue
        for host in parts[0].split(","):
            host = re.sub(r"^\[(.+)\]:\d+$", r"\1", host)
            if host and not re.search(r"[*?!]", host):
                found.setdefault(host, "known host")
    return list(found.items())


def match_targets(typed: str, targets: List[Tuple[str, str]],
                  limit: int = 8) -> List[Tuple[str, str]]:
    """Targets matching what was typed (prefix matches first), keeping a typed `user@`."""
    user, _, query = typed.strip().rpartition("@")
    prefix = user + "@" if user else ""
    q = query.lower()
    starts = [(t, d) for t, d in targets if t.lower().startswith(q)]
    inside = [(t, d) for t, d in targets if q and q in t.lower() and (t, d) not in starts]
    out = [(prefix + t, d) for t, d in starts + inside]
    if len(out) == 1 and out[0][0] == typed.strip():
        return []  # already typed in full
    return out[:limit]


class MatchInput(Input):
    """An input that lists matches below itself while you type: ↑/↓ choose, Enter or Tab
    picks, Esc closes the list. Subclasses provide `find()`; the list is `match_list()`."""

    BINDINGS = [
        Binding("down", "move(1)", show=False),
        Binding("up", "move(-1)", show=False),
        Binding("enter", "pick", show=False),
        Binding("tab", "pick_or_next", show=False),
        Binding("escape", "close", show=False),
    ]

    def __init__(self, *, list_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.list_id = list_id
        self._picked = False

    async def find(self, value: str) -> List[Tuple[str, str]]:  # pragma: no cover
        raise NotImplementedError

    @property
    def matches(self) -> OptionList:
        return self.screen.query_one(f"#{self.list_id}", OptionList)

    @property
    def open(self) -> bool:
        return self.matches.has_class("shown")

    def refresh_matches(self) -> None:
        self.run_worker(self._refresh(), exclusive=True, group=f"matches-{self.id}")

    async def _refresh(self) -> None:
        value = self.value
        found = await self.find(value) if self.has_focus and value.strip() else []
        if value != self.value:
            return  # typed on meanwhile: a newer refresh is coming
        lst = self.matches
        lst.clear_options()
        for target, detail in found:
            prompt = Text(target)
            if detail:
                prompt.append(f"  {detail}", style="dim")
            lst.add_option(Option(prompt, id=target))
        lst.set_class(bool(found), "shown")
        if found:
            lst.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if self._picked:  # just picked: keep the list closed until you type again
            self._picked = False
        else:
            self.refresh_matches()

    def pick(self, value: str) -> None:
        self.matches.remove_class("shown")
        if value != self.value:
            self._picked = True
            self.value = value
        self.cursor_position = len(value)

    def action_move(self, step: int) -> None:
        lst = self.matches
        if self.open and lst.option_count:
            lst.highlighted = ((lst.highlighted or 0) + step) % lst.option_count

    async def action_pick(self) -> None:
        lst = self.matches
        if self.open and lst.highlighted is not None:
            self.pick(lst.get_option_at_index(lst.highlighted).id)
        else:
            await self.action_submit()

    async def action_pick_or_next(self) -> None:
        if self.open:
            await self.action_pick()
        else:
            self.screen.focus_next()

    def action_close(self) -> None:
        if self.open:
            self.matches.remove_class("shown")
        else:
            self.screen.action_cancel()

    def on_focus(self) -> None:
        self.refresh_matches()

    def on_blur(self) -> None:
        # a click on the list lands after this blur: let it pick first
        self.set_timer(0.2, self.refresh_matches)


def match_list(list_id: str) -> OptionList:
    lst = OptionList(id=list_id, compact=True, classes="matches")
    lst.can_focus = False
    return lst


class TargetInput(MatchInput):
    """The SSH target field: lists matching targets from your SSH config."""

    def __init__(self, targets: List[Tuple[str, str]], **kwargs) -> None:
        super().__init__(list_id="ssh-matches", **kwargs)
        self.targets = targets

    async def find(self, value: str) -> List[Tuple[str, str]]:
        return match_targets(value, self.targets)


class FolderInput(MatchInput):
    """The project folder field: lists matching folders on the chosen machine. Picking one
    fills it in with a trailing / so typing on lists what's inside."""

    LIMIT = 50

    def __init__(self, host: Optional[Host], value: str = "", **kwargs) -> None:
        super().__init__(list_id="dir-matches", value=value, **kwargs)
        self.source = PathSuggester(host)

    async def find(self, value: str) -> List[Tuple[str, str]]:
        base = value[: value.rfind("/") + 1]  # as typed: keeps ~ / $HOME
        parent, prefix = os.path.split(norm_path(value))
        if not base and value.startswith("~"):
            return []
        try:
            names = await self.source.dirs(parent)
        except OSError:
            return []
        hidden = prefix.startswith(".")
        names = sorted(n for n in names if hidden or not n.startswith("."))
        low = prefix.lower()
        starts = [n for n in names if n.startswith(prefix)]
        inside = [n for n in names if low and low in n.lower() and n not in starts]
        found = [(base + n + "/", "") for n in starts + inside]
        if len(found) == 1 and found[0][0].rstrip("/") == value.rstrip("/"):
            return []  # already typed in full
        return found[: self.LIMIT]


class Form(ModalScreen):
    """Base for the forms: Esc cancels, Ctrl-S saves, errors shown inline."""

    DEFAULT_CSS = FORM_CSS
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    def buttons(self, save_label: str = "Save") -> ComposeResult:
        yield Static("", classes="error", id="error")
        with Horizontal(classes="buttons"):
            yield Button("Cancel", id="cancel", compact=True)
            yield Button(save_label, id="save", variant="primary", compact=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "save":
            self.action_save()
        elif event.button.id == "cancel":
            self.action_cancel()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_save()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()  # a click in a list of matches: fill in its input
        for inp in self.query(MatchInput):
            if inp.list_id == event.option_list.id:
                inp.pick(str(event.option.id))
                inp.focus()

    def error(self, text: str) -> None:
        log.info("%s: %s", type(self).__name__, text)
        self.query_one("#error", Static).update(text)

    def value(self, wid: str) -> str:
        return self.query_one(f"#{wid}", Input).value.strip()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class SessionForm(Form):
    """Add or edit a session. Dismisses with the new Config, or None if cancelled."""

    def __init__(self, cfg: Config, session: Optional[str] = None, running: bool = False):
        super().__init__()
        self.cfg = copy.deepcopy(cfg)
        self.editing = cfg.session(session) if session else None
        self.running = running
        self._auto_name = self.editing is None

    def compose(self) -> ComposeResult:
        s = self.editing
        local = self.cfg.hosts["local"]
        with Vertical(classes="form"):
            yield Static(f"Edit session “{s.name}”" if s else "New session", classes="title")
            yield Label("Machine")
            yield Select(self._host_options(), allow_blank=False, id="host", compact=True,
                         value=s.host if s else local.name, disabled=self.running)
            yield Label("Project folder")
            yield FolderInput(self.cfg.hosts[s.host] if s else local, s.dir if s else "",
                              placeholder="~/code/my-project", id="dir", compact=True)
            yield match_list("dir-matches")
            yield Static("↑↓ choose a folder · Enter/Tab picks it", classes="hint")
            yield Label("Name")
            yield Input(s.name if s else "", placeholder="my-project", id="name", compact=True,
                        disabled=self.running)
            yield Label("Account")
            yield Select(self._account_options(), allow_blank=False, id="account", compact=True,
                         value=s.account if s else next(iter(self.cfg.accounts)))
            yield Label("Note (optional)")
            yield Input(s.note if s else "", placeholder="what you're working on", id="note",
                        compact=True)
            yield Label("Extra claude flags (optional)")
            yield Input(s.args if s else "", placeholder="e.g. --model opus", id="args",
                        compact=True)
            if self.running:
                yield Static("It's running, so name and machine are locked. Other changes "
                             "apply the next time it starts.", classes="hint")
            yield from self.buttons()

    def on_mount(self) -> None:
        self.query_one("#dir", Input).focus()

    def _host_options(self):
        opts = [(f"{h.name} — {h.label}", h.name) for h in self.cfg.hosts.values()]
        return opts + [("+ add a machine (SSH)…", ADD_HOST)]

    def _account_options(self):
        opts = [(f"{a.name} — {a.config_dir}"
                 + (f" ({a.agent_label})" if a.agent != "claude" else ""), a.name)
                for a in self.cfg.accounts.values()]
        return opts + [("+ add an account…", ADD_ACCOUNT)]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "dir" and self._auto_name:
            name = slug(Path(event.value.rstrip("/")).name) if event.value.strip() else ""
            if name and self.cfg.sessions and any(x.name == name for x in self.cfg.sessions):
                name = f"{name}-2"
            self.query_one("#name", Input).value = name
        elif event.input.id == "name" and event.input.has_focus:
            self._auto_name = False

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value == ADD_HOST:
            self.app.push_screen(HostForm(self.cfg), self._host_added)
        elif event.value == ADD_ACCOUNT:
            self.app.push_screen(AccountForm(self.cfg), self._account_added)
        elif event.select.id == "host":
            self.query_one("#dir", FolderInput).source = PathSuggester(
                self.cfg.hosts.get(str(event.value)))

    def _host_added(self, host: Optional[Host]) -> None:
        sel = self.query_one("#host", Select)
        if host:
            self.cfg.hosts[host.name] = host
            sel.set_options(self._host_options())
        sel.value = host.name if host else (self.editing.host if self.editing else "local")

    def _account_added(self, account: Optional[Account]) -> None:
        sel = self.query_one("#account", Select)
        if account:
            self.cfg.accounts[account.name] = account
            sel.set_options(self._account_options())
        sel.value = account.name if account else (
            self.editing.account if self.editing else next(iter(self.cfg.accounts)))

    def action_save(self) -> None:
        name, d = self.value("name"), norm_path(self.value("dir"))
        d = d.rstrip("/") or d  # a picked folder ends in /
        host = str(self.query_one("#host", Select).value)
        account = str(self.query_one("#account", Select).value)
        if not d:
            return self.error("Choose a project folder.")
        if not name or not NAME_RE.match(name):
            return self.error("Name: use letters, digits, _ . - (no spaces, not starting with .).")
        if host not in self.cfg.hosts or account not in self.cfg.accounts:
            return self.error("Pick a machine and an account.")
        if host == "local" and not os.path.isdir(os.path.expanduser(d)):
            return self.error(f"Folder not found on this Mac: {d}")
        new = SessionDef(name=name, host=host, dir=d, account=account,
                         note=self.value("note"), args=self.value("args"))
        sessions = list(self.cfg.sessions)
        if self.editing:
            sessions = [new if x.name == self.editing.name else x for x in sessions]
        else:
            sessions.append(new)
        self.cfg.sessions = sessions
        try:
            result = parse(to_dict(self.cfg), self.cfg.path)
        except ConfigError as e:
            return self.error(str(e))
        self.dismiss(result)


class HostForm(Form):
    """Add an SSH machine. Dismisses with a Host or None."""

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg

    def compose(self) -> ComposeResult:
        with Vertical(classes="form"):
            yield Static("Add a machine", classes="title")
            yield Label("SSH target")
            yield TargetInput(ssh_targets(), placeholder="user@my-vm  (or an alias from "
                              "~/.ssh/config)", id="ssh", compact=True)
            yield match_list("ssh-matches")
            yield Static("Must work without a password: ssh <target> true", classes="hint")
            yield Label("Short name")
            yield Input(compact=True, placeholder="vm", id="name")
            yield Label("Claude command on that machine (optional)")
            yield Input(compact=True, placeholder="claude", id="claude")
            yield from self.buttons("Add machine")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "ssh":
            target = event.value.strip().split("@")[-1].split(".")[0]
            name = self.query_one("#name", Input)
            if not name.has_focus:
                name.value = slug(target)

    def action_save(self) -> None:
        ssh, name = self.value("ssh"), self.value("name")
        if not ssh:
            return self.error("Enter the SSH target.")
        if not name or not NAME_RE.match(name):
            return self.error("Short name: use letters, digits, _ . -")
        if name in self.cfg.hosts:
            return self.error(f"There's already a machine called {name}.")
        self.dismiss(Host(name, ssh, self.value("claude") or "claude"))


API_KEY_VAR = {"claude": "ANTHROPIC_API_KEY", "codex": "OPENAI_API_KEY"}


class AccountForm(Form):
    """Add an account: an agent (Claude Code or Codex) and its config folder. Dismisses
    with an Account or None."""

    def __init__(self, cfg: Config):
        super().__init__()
        self.cfg = cfg

    def compose(self) -> ComposeResult:
        with Vertical(classes="form"):
            yield Static("Add an account", classes="title")
            yield Label("Agent")
            yield Select([(info["label"], agent) for agent, info in AGENTS.items()],
                         allow_blank=False, value="claude", id="agent", compact=True)
            yield Label("Name")
            yield Input(compact=True, placeholder="work", id="name")
            yield Label("Config folder")
            yield Input(compact=True, placeholder="~/.claude-work", id="config_dir")
            yield Static("", classes="hint", id="dir-hint")
            yield Label("API key (optional)")
            yield Input(compact=True, password=True, id="api_key")
            yield from self.buttons("Add account")

    def on_mount(self) -> None:
        self._agent_changed()

    @property
    def agent(self) -> str:
        return str(self.query_one("#agent", Select).value)

    def _agent_changed(self) -> None:
        agent, info = self.agent, AGENTS[self.agent]
        prefix = info["dir"]
        self.query_one("#config_dir", Input).placeholder = f"{prefix}-work"
        self.query_one("#dir-hint", Static).update(
            f"Each account keeps its own login here. {prefix} is the default "
            f"{info['label']} one you already use.")
        login = "/login" if agent == "claude" else "codex login"
        key = "sk-ant-…" if agent == "claude" else "sk-…"
        self.query_one("#api_key", Input).placeholder = (
            f"{key}  leave empty to log in with {login}")
        self._fill_dir()

    def _fill_dir(self) -> None:
        cdir = self.query_one("#config_dir", Input)
        if not cdir.has_focus:
            n = slug(self.query_one("#name", Input).value)
            cdir.value = f"{AGENTS[self.agent]['dir']}-{n}" if n else ""

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "agent":
            self._agent_changed()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "name":
            self._fill_dir()

    def action_save(self) -> None:
        name = self.value("name")
        if not name or not NAME_RE.match(name):
            return self.error("Name: use letters, digits, _ . -")
        if name in self.cfg.accounts:
            return self.error(f"There's already an account called {name}.")
        agent = self.agent
        cdir = norm_path(self.value("config_dir")) or f"{AGENTS[agent]['dir']}-{name}"
        key = self.value("api_key")
        env = {API_KEY_VAR[agent]: key} if key else {}
        self.dismiss(Account(name, cdir, env, agent))


class Confirm(ModalScreen):
    """Yes/No question. Dismisses with True/False."""

    DEFAULT_CSS = FORM_CSS
    BINDINGS = [Binding("escape", "no", "No"), Binding("y", "yes", "Yes"),
                Binding("n", "no", "No")]

    def __init__(self, question: str, yes: str = "Yes", no: str = "No"):
        super().__init__()
        self.question, self.yes, self.no = question, yes, no

    def compose(self) -> ComposeResult:
        with Vertical(classes="form"):
            yield Static(self.question)
            with Horizontal(classes="buttons"):
                yield Button(self.no, id="no", compact=True)
                yield Button(self.yes, id="yes", variant="primary", compact=True)

    def on_mount(self) -> None:
        self.query_one("#yes", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


def new_pairs(old: Config, new: Config) -> List[str]:
    """Host names that gained a (host, account folder) pair in `new`, i.e. need hooks
    installed: a new host or account for a session, or an account's config_dir changed."""
    def pairs(cfg: Config):
        return {(s.host, cfg.account_of(s).config_dir) for s in cfg.sessions}
    before = pairs(old)
    hosts: List[str] = []
    for s in new.sessions:
        if (s.host, new.account_of(s).config_dir) not in before and s.host not in hosts:
            hosts.append(s.host)
    return hosts


class ResumePicker(ModalScreen):
    """Pick a past conversation of a session to resume. Dismisses with its id or None."""

    DEFAULT_CSS = FORM_CSS
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, cfg: Config, name: str, current: str = ""):
        super().__init__()
        self.cfg, self.session_name, self.current = cfg, name, current

    def compose(self) -> ComposeResult:
        s = self.cfg.session(self.session_name)
        with Vertical(classes="form picker"):
            yield Static(f"Resume a conversation in “{s.name}”", classes="title")
            yield Static(f"{s.dir} · {s.account}@{s.host}", classes="hint")
            yield Static("loading…", id="picker-status", classes="hint")
            lst = OptionList(id="conversations", compact=True)
            lst.display = False
            yield lst
            yield Static("↑↓ choose · Enter resumes · Esc cancels", classes="hint")

    def on_mount(self) -> None:
        self.load()

    @work(thread=True, exclusive=True)
    def load(self) -> None:
        try:
            items = sessions.conversations(self.cfg, self.session_name)
        except sessions.SessionError as e:
            self.app.call_from_thread(self.show_error, str(e))
            return
        except Exception as e:
            log.exception("listing conversations of %s failed", self.session_name)
            self.app.call_from_thread(self.show_error, f"couldn't list conversations: {e}")
            return
        self.app.call_from_thread(self.show, items)

    def show_error(self, text: str) -> None:
        self.query_one("#picker-status", Static).update(Text(text, style="bold red"))

    def show(self, items: List["sessions.Conversation"]) -> None:
        status = self.query_one("#picker-status", Static)
        if not items:
            status.update("No past conversations in this folder for this account yet.")
            return
        status.display = False
        lst = self.query_one("#conversations", OptionList)
        for c in items:
            lst.add_option(Option(self.describe(c), id=c.id))
        lst.display = True
        lst.focus()
        ids = [c.id for c in items]
        lst.highlighted = ids.index(self.current) if self.current in ids else 0

    def describe(self, c: "sessions.Conversation") -> Text:
        t = Text(one_line(c.title or c.first, 80), style="bold")
        t.append(f"  {sessions.age(c.mtime)} ago", style="dim")
        if c.id == self.current:
            t.append("  · last used here", style="italic #f5b942")
        detail = c.last if c.title or (c.last and c.last != c.first) else ""
        if c.title and not detail:
            detail = c.first
        if detail:
            t.append(f"\n  {one_line(detail, 96)}", style="dim")
        return t

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(str(event.option.id))

    def action_cancel(self) -> None:
        self.dismiss(None)


def one_line(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
