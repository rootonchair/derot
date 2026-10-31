"""Load and validate ~/.config/derot/config.yaml."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .log import log

NAME_RE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$")
DEFAULT_CONFIG_DIR = "~/.claude"

# The coding agents derot can run. Each account belongs to one: its folder is that agent's
# config folder (CLAUDE_CONFIG_DIR / CODEX_HOME).
AGENTS = {
    "claude": {"label": "Claude Code", "dir": "~/.claude", "env": "CLAUDE_CONFIG_DIR"},
    "codex": {"label": "Codex", "dir": "~/.codex", "env": "CODEX_HOME"},
}


class ConfigError(Exception):
    """A one-line, user-facing configuration problem."""


@dataclass
class Host:
    name: str
    ssh: Optional[str] = None
    claude: str = "claude"
    codex: str = "codex"

    def command(self, agent: str) -> str:
        """The command (or full path) for an agent on this machine."""
        return self.codex if agent == "codex" else self.claude

    @property
    def is_local(self) -> bool:
        return self.ssh is None

    @property
    def label(self) -> str:
        return "this Mac" if self.is_local else str(self.ssh)


@dataclass
class Account:
    name: str
    config_dir: str = DEFAULT_CONFIG_DIR
    env: Dict[str, str] = field(default_factory=dict)
    agent: str = "claude"

    @property
    def default_dir(self) -> str:
        return AGENTS[self.agent]["dir"]

    @property
    def dir_env(self) -> str:
        """The variable that points the agent at this account's folder."""
        return AGENTS[self.agent]["env"]

    @property
    def agent_label(self) -> str:
        return AGENTS[self.agent]["label"]

    @property
    def is_default_dir(self) -> bool:
        """True for the agent's default folder, however it is written (on this machine)."""
        d = self.config_dir.rstrip("/")
        if d == self.default_dir:
            return True
        return os.path.expanduser(d) == os.path.expanduser(self.default_dir)


@dataclass
class SessionDef:
    name: str
    host: str
    dir: str
    account: str
    note: str = ""
    args: str = ""


@dataclass
class Notify:
    on_waiting: bool = True
    on_done: bool = True
    sound: str = "Glass"


@dataclass
class Config:
    hosts: Dict[str, Host]
    accounts: Dict[str, Account]
    sessions: List[SessionDef]
    notify: Notify = field(default_factory=Notify)
    refresh: float = 3
    detach_key: str = "C-q"
    path: Optional[Path] = None

    def session(self, name: str) -> SessionDef:
        for s in self.sessions:
            if s.name == name:
                return s
        raise ConfigError(f"no session named '{name}' in the config")

    def host_of(self, s: SessionDef) -> Host:
        return self.hosts[s.host]

    def account_of(self, s: SessionDef) -> Account:
        return self.accounts[s.account]

    def used_hosts(self) -> List[Host]:
        """Hosts that have at least one session, in config order."""
        seen: List[str] = []
        for s in self.sessions:
            if s.host not in seen:
                seen.append(s.host)
        return [self.hosts[h] for h in seen]

    def accounts_on(self, host: str) -> List[Account]:
        seen: List[str] = []
        for s in self.sessions:
            if s.host == host and s.account not in seen:
                seen.append(s.account)
        return [self.accounts[a] for a in seen]


def config_path() -> Path:
    env = os.environ.get("DEROT_CONFIG")
    if env:
        return Path(env).expanduser()
    return Path("~/.config/derot/config.yaml").expanduser()


def example_text() -> str:
    return (Path(__file__).parent / "example_config.yaml").read_text()


def ensure_config(path: Optional[Path] = None) -> bool:
    """Write the example config if missing. Returns True if it was created."""
    path = path or config_path()
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(example_text())
    os.chmod(path, 0o600)
    return True


def norm_path(path: str) -> str:
    """`$HOME/x` / `${HOME}/x` -> `~/x`: everything downstream expands `~` (shell and
    Python alike), but a quoted `$HOME` would reach Claude as a literal relative path."""
    for prefix in ("${HOME}", "$HOME"):
        if path == prefix or path.startswith(prefix + "/"):
            return "~" + path[len(prefix):]
    return path


def _mapping(value, where: str) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{where}: expected a mapping")
    return value


def _str(value, where: str, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        raise ConfigError(f"{where}: expected a string")
    return str(value)


def parse(data, path: Optional[Path] = None) -> Config:
    data = _mapping(data, "config")

    hosts: Dict[str, Host] = {"local": Host("local")}
    for name, h in _mapping(data.get("hosts"), "hosts").items():
        name = str(name)
        h = _mapping(h, f"host '{name}'")
        claude = _str(h.get("claude"), f"host '{name}' claude", "claude") or "claude"
        codex = _str(h.get("codex"), f"host '{name}' codex", "codex") or "codex"
        if name == "local":
            hosts["local"] = Host("local", None, claude, codex)
            continue
        ssh = _str(h.get("ssh"), f"host '{name}' ssh")
        if not ssh:
            raise ConfigError(f"host '{name}': missing 'ssh' (e.g. ssh: user@my-vm)")
        hosts[name] = Host(name, ssh, claude, codex)

    accounts: Dict[str, Account] = {}
    for name, a in _mapping(data.get("accounts"), "accounts").items():
        name = str(name)
        a = _mapping(a, f"account '{name}'")
        agent = _str(a.get("agent"), f"account '{name}' agent", "claude") or "claude"
        if agent not in AGENTS:
            raise ConfigError(f"account '{name}': unknown agent '{agent}' (use "
                              + " or ".join(AGENTS) + ")")
        default = AGENTS[agent]["dir"]
        cdir = _str(a.get("config_dir"), f"account '{name}' config_dir", default)
        env = {
            str(k): _str(v, f"account '{name}' env {k}")
            for k, v in _mapping(a.get("env"), f"account '{name}' env").items()
        }
        accounts[name] = Account(name, norm_path(cdir or default), env, agent)
    if not accounts:
        accounts["default"] = Account("default", DEFAULT_CONFIG_DIR)

    raw_sessions = data.get("sessions") or []
    if not isinstance(raw_sessions, list):
        raise ConfigError("sessions: expected a list")
    sessions: List[SessionDef] = []
    names = set()
    tmux_keys: Dict[str, str] = {}
    for i, s in enumerate(raw_sessions):
        s = _mapping(s, f"session #{i + 1}")
        name = _str(s.get("name"), f"session #{i + 1} name")
        label = f"session '{name}'" if name else f"session #{i + 1}"
        if not name or not NAME_RE.match(name):
            raise ConfigError(f"{label}: invalid name (use letters, digits, _ . -; not starting with .)")
        if name in names:
            raise ConfigError(f"{label}: duplicate session name")
        clash = tmux_keys.get(name.replace(".", "_"))
        if clash:  # tmux names write `.` as `_`
            raise ConfigError(f"{label}: too similar to session '{clash}' (. and _ count "
                              "as the same in tmux session names)")
        names.add(name)
        tmux_keys[name.replace(".", "_")] = name
        host = _str(s.get("host"), f"{label} host", "local") or "local"
        if host not in hosts:
            raise ConfigError(f"{label}: unknown host '{host}'")
        if len(accounts) == 1 and not s.get("account"):
            account = next(iter(accounts))
        else:
            account = _str(s.get("account"), f"{label} account")
        if account not in accounts:
            raise ConfigError(f"{label}: unknown account '{account}'")
        d = _str(s.get("dir"), f"{label} dir")
        if not d:
            raise ConfigError(f"{label}: missing 'dir'")
        sessions.append(SessionDef(
            name=name, host=host, dir=norm_path(d), account=account,
            note=_str(s.get("note"), f"{label} note"),
            args=_str(s.get("args"), f"{label} args"),
        ))

    n = _mapping(data.get("notify"), "notify")
    notify = Notify(
        on_waiting=bool(n.get("on_waiting", True)),
        on_done=bool(n.get("on_done", True)),
        sound=_str(n.get("sound", "Glass"), "notify sound"),
    )

    try:
        refresh = float(data.get("refresh", 3))
    except (TypeError, ValueError):
        raise ConfigError("refresh: expected a number of seconds")
    if not 0 < refresh <= 3600:  # also rejects .inf and .nan
        raise ConfigError("refresh: expected a number of seconds between 1 and 3600")
    refresh = max(1.0, refresh)
    detach_key = _str(data.get("detach_key"), "detach_key", "C-q") or "C-q"

    return Config(hosts, accounts, sessions, notify, refresh, detach_key, path)


SAVED_HEADER = """\
# derot configuration (edited from the derot console; comments are not kept).
# Hosts: machines ("local" is this computer). Accounts: Claude Code or Codex folders.
# Sessions: a project folder + machine + account. See the README for every option.
"""


def to_dict(cfg: Config) -> dict:
    """The YAML-ready form of cfg, leaving out values that are at their defaults."""
    hosts: dict = {}
    for h in cfg.hosts.values():
        entry: dict = {}
        if not h.is_local:
            entry["ssh"] = h.ssh
        if h.claude != "claude":
            entry["claude"] = h.claude
        if h.codex != "codex":
            entry["codex"] = h.codex
        if entry or not h.is_local:
            hosts[h.name] = entry
    accounts: dict = {}
    for a in cfg.accounts.values():
        entry = {"config_dir": a.config_dir}
        if a.agent != "claude":
            entry = {"agent": a.agent, **entry}
        if a.env:
            entry["env"] = dict(a.env)
        accounts[a.name] = entry
    sessions = []
    for s in cfg.sessions:
        entry = {"name": s.name, "host": s.host, "dir": s.dir, "account": s.account}
        if s.note:
            entry["note"] = s.note
        if s.args:
            entry["args"] = s.args
        sessions.append(entry)
    data: dict = {}
    if hosts:
        data["hosts"] = hosts
    data["accounts"] = accounts
    data["sessions"] = sessions
    data["notify"] = {"on_waiting": cfg.notify.on_waiting, "on_done": cfg.notify.on_done,
                      "sound": cfg.notify.sound}
    data["refresh"] = int(cfg.refresh) if cfg.refresh == int(cfg.refresh) else cfg.refresh
    data["detach_key"] = cfg.detach_key
    return data


def save(cfg: Config, path: Optional[Path] = None) -> Config:
    """Validate and write cfg. Keeps a one-time backup of the hand-written file."""
    path = path or cfg.path or config_path()
    data = to_dict(cfg)
    checked = parse(data, path)  # raises ConfigError if the change made it invalid
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_name(path.name + ".bak")
    if path.exists() and not backup.exists():
        backup.write_text(path.read_text())
    tmp = path.with_name(f".{path.name}.tmp")
    text = SAVED_HEADER + "\n" + yaml.safe_dump(
        data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    # 0600: the config can hold API keys (account env)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    if backup.exists():
        os.chmod(backup, 0o600)
    log.info("saved config %s (%d sessions, accounts: %s, hosts: %s)", path,
             len(checked.sessions), ", ".join(checked.accounts), ", ".join(checked.hosts))
    return checked


def load(path: Optional[Path] = None) -> Config:
    path = path or config_path()
    try:
        text = path.read_text()
    except FileNotFoundError:
        raise ConfigError(f"config not found: {path} (run `derot init`)")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark else ""
        problem = getattr(e, "problem", None) or "parse error"
        raise ConfigError(f"invalid YAML in {path}{where}: {problem}")
    return parse(data, path)
