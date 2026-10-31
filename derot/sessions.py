"""Session operations: poll, start, stop, attach, mark_seen."""

from __future__ import annotations

import json
import re
import shlex
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import remote
from .config import Account, Config, Host, SessionDef
from .log import log

TMUX = ["tmux", "-L", "derot"]
ORDER = ["waiting", "done", "busy", "idle", "stopped", "offline"]

# state -> (icon, label, color, bold)
STYLE = {
    "waiting": ("◆", "needs you", "#f5b942", True),
    "done": ("✓", "done", "#5fd68a", True),
    "busy": ("●", "working", "#5ab8f0", False),
    "idle": ("○", "idle", "#9aa0a6", False),
    "stopped": ("–", "stopped", "#5f6368", False),
    "offline": ("✗", "offline", "#e06c75", False),
}

POLL_SCRIPT = r"""
echo "@@TMUX"
tmux -L derot list-sessions -F '#{session_name}|#{session_attached}|#{session_created}' 2>/dev/null | grep '^cc-' || true
echo "@@NOW"
date +%s
echo "@@STATE"
if grep -q -- '--dump' "$HOME/.derot/hook.py" 2>/dev/null; then
  python3 "$HOME/.derot/hook.py" --dump 2>/dev/null
else
  for f in "$HOME"/.derot/state/*.json; do [ -f "$f" ] && { cat "$f"; echo; }; done
fi
echo "@@HOOK"
[ -f "$HOME/.derot/hook.py" ] && echo yes || echo no
echo "@@END"
"""

MARK_SEEN = r"""
import json, os, sys, tempfile
p = os.path.expanduser("~/.derot/state/%s.json" % sys.argv[1])
try:
    with open(p) as f:
        d = json.load(f)
except Exception:
    sys.exit(0)
if isinstance(d, dict) and d.get("state") == "done":
    d["state"] = "idle"
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)
    os.replace(tmp, p)
"""

# You answered a permission prompt from derot: no hook fires on approval, so without this
# a long approved tool shows "needs you" until it finishes. Only if the state is still the
# one the console saw (same ts), so a newer prompt is never overwritten.
MARK_ANSWERED = r"""
import json, os, sys, tempfile
p = os.path.expanduser("~/.derot/state/%s.json" % sys.argv[1])
try:
    with open(p) as f:
        d = json.load(f)
    seen = float(sys.argv[2])
except Exception:
    sys.exit(0)
if isinstance(d, dict) and d.get("state") == "waiting" \
        and abs(float(d.get("ts") or 0) - seen) < 0.001:
    d["state"], d["message"] = "busy", "answered, working…"
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(p), prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        json.dump(d, f)
    os.replace(tmp, p)
"""

HOOK_MISSING = "status hooks not installed: run `derot setup`"
NO_STATUS = ("Claude hasn't started yet, probably a login, trust or first-run screen "
             "(Enter or click to answer it; if nothing's there, press u)")
# Codex skips hooks nobody has approved yet, so that's the likeliest reason for silence
NO_STATUS_CODEX = ("Codex isn't reporting yet, probably derot's hooks waiting for approval "
                   "in /hooks, or a login or trust screen (Enter or click to answer it)")
NO_STATUS_SECS = 15

_online: Dict[str, bool] = {}  # last known reachability per host, to log only changes


class SessionError(Exception):
    pass


@dataclass
class Status:
    sdef: SessionDef
    host: Host
    account: Account
    state: str = "stopped"
    message: str = ""
    prompt: str = ""
    ts: float = 0.0
    attached: bool = False
    transcript: str = ""  # Claude's transcript path on the host (from the hook)
    alerts: int = 0  # the hook's count of alert-worthy events (0 from older hooks)
    session_id: str = ""  # Claude's conversation id, kept after the session stops

    @property
    def name(self) -> str:
        return self.sdef.name

    @property
    def running(self) -> bool:
        return self.state not in ("stopped", "offline")

    @property
    def where(self) -> str:
        return f"{self.account.name}@{self.host.name}"


@dataclass
class HostPoll:
    online: bool
    error: str = ""
    tmux: Dict[str, bool] = field(default_factory=dict)  # session name -> attached
    age: Dict[str, float] = field(default_factory=dict)  # session name -> seconds running
    states: Dict[str, dict] = field(default_factory=dict)
    hook: bool = False


# ---------------------------------------------------------------- polling

def parse_poll(out: str) -> Optional[HostPoll]:
    if "@@END" not in out:
        return None
    hp = HostPoll(online=True)
    section = None
    created_at: Dict[str, int] = {}
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("@@"):
            section = line
            continue
        if not line:
            continue
        if section == "@@TMUX":
            name, _, rest = line.partition("|")
            attached, _, created = rest.partition("|")
            if name.startswith("cc-"):
                hp.tmux[name[3:]] = attached.strip() not in ("", "0")
                if created.strip().isdigit():
                    created_at[name[3:]] = int(created)
        elif section == "@@NOW":
            if line.isdigit():  # the host's clock, so a skewed local clock doesn't matter
                for name, t in created_at.items():
                    hp.age[name] = int(line) - t
        elif section == "@@STATE":
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and d.get("session"):
                hp.states[str(d["session"])] = d
        elif section == "@@HOOK":
            hp.hook = line == "yes"
    return hp


def poll_host(host: Host) -> HostPoll:
    proc = remote.sh(host, POLL_SCRIPT, timeout=15)
    hp = parse_poll(proc.stdout) if proc.returncode == 0 else None
    was = _online.get(host.name)
    if hp is None:
        if was is not False:
            log.warning("host %s is unreachable (rc=%s): %s", host.name, proc.returncode,
                        remote.full_error(proc))
        _online[host.name] = False
        return HostPoll(online=False, error=remote.error_text(proc))
    if was is False:
        log.info("host %s is reachable again", host.name)
    _online[host.name] = True
    return hp


def resolve(cfg: Config, s: SessionDef, hp: HostPoll) -> Status:
    st = Status(s, cfg.host_of(s), cfg.account_of(s))
    if not hp.online:
        st.state, st.message = "offline", hp.error
        return st
    data = hp.states.get(s.name) or {}
    st.prompt = str(data.get("prompt") or "")
    st.transcript = str(data.get("transcript_path") or "")
    st.session_id = str(data.get("session_id") or "")
    try:
        st.alerts = int(data.get("alerts") or 0)
    except (TypeError, ValueError):
        pass
    try:
        st.ts = float(data.get("ts") or 0)
    except (TypeError, ValueError):
        st.ts = 0.0
    last = data.get("state")
    key = tmux_name(s.name)[3:]  # how the poll lists it
    if key not in hp.tmux:
        st.state = "stopped"
        if last in ("done", "stopped"):
            st.message = str(data.get("message") or "")
        return st
    st.attached = hp.tmux[key]
    if data and last in STYLE and last not in ("stopped", "offline"):
        st.state = str(last)
        st.message = str(data.get("message") or "")
    else:
        st.state = "idle"
        if not hp.hook:
            st.message = HOOK_MISSING
        elif not data and hp.age.get(key, 0) > NO_STATUS_SECS:
            # start deletes the state file and SessionStart writes it straight away, unless
            # Claude is stuck before the session starts: "trust this folder?", a new
            # account's login / first-run screens (seen on 2.1.316; no hook fires for them)
            st.state = "waiting"
            st.message = NO_STATUS_CODEX if st.account.agent == "codex" else NO_STATUS
    return st


def sort_key(st: Status):
    return (ORDER.index(st.state) if st.state in ORDER else len(ORDER), -st.ts, st.name)


def poll(cfg: Config) -> List[Status]:
    """Poll every host that has sessions (in parallel) and return sorted statuses."""
    statuses, _ = poll_full(cfg)
    return statuses


def poll_full(cfg: Config):
    """Like poll() but also returns {host name: error} for unreachable hosts."""
    hosts = cfg.used_hosts()
    results: Dict[str, HostPoll] = {}
    if hosts:
        with ThreadPoolExecutor(max_workers=min(8, len(hosts))) as pool:
            for h, hp in zip(hosts, pool.map(poll_host, hosts)):
                results[h.name] = hp
    statuses = [resolve(cfg, s, results[s.host]) for s in cfg.sessions]
    statuses.sort(key=sort_key)
    offline = {name: hp.error for name, hp in results.items() if not hp.online}
    return statuses, offline


# ---------------------------------------------------------------- start / stop

def _cmd(word: str) -> str:
    """Quote a command/path from config; leave multi-word commands (e.g. `npx x`) as is."""
    return word if any(c.isspace() for c in word) else remote.qpath(word)


def tmux_name(name: str) -> str:
    """tmux session name for a session: `cc-<name>`, with `.` written as `_` (older tmux,
    e.g. 3.4 on Ubuntu 24.04, silently renames `a.b` to `a_b`; config rejects names that
    would clash this way)."""
    return "cc-" + name.replace(".", "_")


def target(name: str) -> str:
    """Exact tmux target for a session. `=` stops prefix matching (stop `api` must never
    hit `api-v2`); the trailing `:` stops anything after it being read as a window."""
    return f"={tmux_name(name)}:"


def env_file(key: str) -> str:
    """Per-session file (0600) holding the account's env vars, sourced (and deleted) by the
    pane, so secrets never appear on a command line (`ps`)."""
    return f'"$HOME/.derot/env/{key}.sh"'


def env_content(account: Account) -> str:
    return "".join(
        f"export {k}={shlex.quote(v)}\n" for k, v in account.env.items()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", k))


def write_env_script(key: str) -> str:
    """Shell that stores stdin as the env file. umask only inside the subshell, so panes
    (and the files Claude creates) keep the normal umask."""
    return f'(umask 077; mkdir -p "$HOME/.derot/env" && cat > {env_file(key)})'


def key_label(key: str) -> str:
    """tmux key name -> human label: C-q -> Ctrl-q, M-x -> Alt-x."""
    return key.replace("C-", "Ctrl-").replace("M-", "Alt-").replace("S-", "Shift-")


def env_lines(account: Account, key: str) -> List[str]:
    """Pane setup for an account. The default-folder test runs on the host, so `~/.claude`,
    `$HOME/.claude` and an absolute path to it all keep the agent's normal login (same for
    Codex's `~/.codex` and CODEX_HOME)."""
    default, var = account.default_dir[2:], account.dir_env  # ".claude" / ".codex"
    return [
        "unset CLAUDECODE",
        f"derot_dir={remote.qpath(account.config_dir)}",
        f'if [ "${{derot_dir%/}}" = "$HOME/{default}" ]; then unset {var}; '
        f'else export {var}="$derot_dir"; fi; unset derot_dir',
        # read once, then delete: the secrets live only in the session's processes, not
        # on the host's disk after the session is stopped or removed
        f"if [ -f {env_file(key)} ]; then . {env_file(key)}; rm -f {env_file(key)}; fi",
    ]


def inner_script(cfg: Config, s: SessionDef, cont: bool, resume: str = "",
                 resume_file: str = "") -> str:
    host, account = cfg.host_of(s), cfg.account_of(s)
    if account.agent == "codex":
        return _script(s, account, _codex_cmd(host, s, cont, resume, resume_file), "codex")
    base = " ".join(p for p in [_cmd(host.claude), s.args.strip()] if p)
    if resume and resume_file:
        # the session's own last conversation, if anything was said in it (Claude only
        # writes the transcript with the first message); otherwise the folder's newest
        claude = (f"if [ -f {remote.qpath(resume_file)} ]; then {base} --resume "
                  f"{shlex.quote(resume)}; else {base} --continue; fi")
    elif resume:
        claude = f"{base} --resume {shlex.quote(resume)}"
    else:
        claude = f"{base} --continue" if cont else base
    return _script(s, account, claude, "claude")


def _codex_cmd(host: Host, s: SessionDef, cont: bool, resume: str, resume_file: str) -> str:
    """codex / codex resume ID / codex resume --last; the session's flags go after
    `resume`, which takes the same options."""
    base = _cmd(host.codex)
    args = s.args.strip()
    fresh = " ".join(p for p in [base, args] if p)
    again = " ".join(p for p in [base, "resume", args] if p)
    if resume and resume_file:
        return (f"if [ -f {remote.qpath(resume_file)} ]; then {again} "
                f"{shlex.quote(resume)}; else {again} --last; fi")
    if resume:
        return f"{again} {shlex.quote(resume)}"
    return f"{again} --last" if cont else fresh


def _script(s: SessionDef, account: Account, command: str, what: str) -> str:
    missing = shlex.quote(f"[derot] folder not found: {s.dir}")
    lines = [f"export DEROT_SESSION={s.name}", *env_lines(account, s.name)]
    lines += [
        f"cd {remote.qpath(s.dir)} || {{ echo {missing}; read _; exit 1; }}",
        f"{command}; code=$?",
        'if [ "$code" -ne 0 ]; then '
        f'echo "[derot] {what} exited with code $code. Press Enter to close."; read _; fi',
    ]
    return "\n".join(lines)


def run_file(key: str) -> str:
    return f'"$HOME/.derot/run/{key}.sh"'


def write_run_script(key: str, script: str) -> str:
    """Shell that stores the pane's script (no secrets: those are in the env file)."""
    return (f'mkdir -p "$HOME/.derot/run" && printf "%s\\n" {shlex.quote(script)}'
            f' > {run_file(key)}')


def launch_cmd(key: str) -> str:
    """Run a stored script through the user's login shell, so PATH and the rest of their
    setup apply. The script is POSIX sh: bash/zsh/ksh source it (their aliases still work),
    any other shell (fish, csh, ...) just hands it to /bin/sh. Runs under /bin/sh itself."""
    f = run_file(key)
    return (f'f={f}; case "${{SHELL##*/}}" in '
            'sh|bash|zsh|dash|ksh|mksh|"") exec "${SHELL:-/bin/sh}" -lic ". \\"$f\\"";; '
            '*) exec "$SHELL" -lic "exec /bin/sh \\"$f\\"";; esac')


def pane_cmd(cfg: Config, s: SessionDef, cont: bool = False) -> str:
    return launch_cmd(s.name)


def _fmt(text: str) -> str:
    return text.replace("#", "##")


def start_script(cfg: Config, s: SessionDef, cont: bool = False, resume: str = "",
                 resume_file: str = "") -> str:
    host = cfg.host_of(s)
    new = TMUX + [
        "start-server", ";",
        "set-option", "-g", "history-limit", "50000", ";",
        # panes start under /bin/sh whatever the login shell is (see launch_cmd)
        "set-option", "-g", "default-shell", "/bin/sh", ";",
        "new-session", "-d", "-s", tmux_name(s.name), "-x", "220", "-y", "60",
        pane_cmd(cfg, s, cont),
    ]
    left = _fmt(f" derot · {s.name} · {s.account}@{host.name} ")
    right = _fmt(f"{key_label(cfg.detach_key)}: back to derot ")
    opts = TMUX + [
        "set-option", "-g", "status-style", "bg=colour235,fg=colour245", ";",
        "set-option", "-g", "window-status-format", "", ";",
        "set-option", "-g", "window-status-current-format", "", ";",
        "set-option", "-g", "status-right", right, ";",
        "set-option", "-g", "status-right-length", "60", ";",
        "set-option", "-t", target(s.name), "status-left", left, ";",
        "set-option", "-t", target(s.name), "status-left-length", "100", ";",
        "bind-key", "-n", cfg.detach_key, "detach-client",
    ]
    has = shlex.join(TMUX + ["has-session", "-t", target(s.name)])
    # once the env file is written only the pane deletes it: if no pane starts, do it here,
    # or the account's secrets stay on the host
    fail = f"{{ rc=$?; rm -f {env_file(s.name)}; exit $rc; }}"
    return "\n".join([
        # check first: never touch the state of a session that is already running
        f"if {has} 2>/dev/null; then echo 'duplicate session: {tmux_name(s.name)}' >&2; exit 1; fi",
        f"[ -d {remote.qpath(s.dir)} ] || {{ echo {shlex.quote('folder not found: ' + s.dir)}"
        f" >&2; exit 1; }}",
        write_env_script(s.name) + " || " + fail,
        write_run_script(s.name, inner_script(cfg, s, cont, resume, resume_file))
        + " || " + fail,
        f'rm -f "$HOME/.derot/state/{s.name}.json"',
        shlex.join(new) + " || " + fail,
        shlex.join(opts) + " >/dev/null",
    ])


def start(cfg: Config, name: str, cont: bool = False, resume: str = "",
          resume_file: str = "") -> None:
    """Start a session: fresh, `cont` = the folder's newest conversation (--continue), or
    `resume` = that conversation id (--resume). With `resume_file` (its transcript), fall
    back to --continue if that file doesn't exist."""
    s = cfg.session(name)
    log.info("starting %s on %s (account %s, dir %s)%s", name, s.host, s.account, s.dir,
             f" resuming {resume}" if resume else " with --continue" if cont else "")
    proc = remote.sh(cfg.host_of(s), start_script(cfg, s, cont, resume, resume_file),
                     input=env_content(cfg.account_of(s)))
    if proc.returncode != 0:
        err = remote.error_text(proc)
        if "duplicate session" in err:
            log.info("%s is already running", name)
            raise SessionError(f"`{name}` is already running")
        log.error("couldn't start %s (rc=%s): %s", name, proc.returncode, remote.full_error(proc))
        raise SessionError(f"couldn't start `{name}`: {err}")


def stop(cfg: Config, name: str) -> None:
    s = cfg.session(name)
    log.info("stopping %s on %s", name, s.host)
    proc = remote.run(cfg.host_of(s), TMUX + ["kill-session", "-t", target(name)])
    if proc.returncode != 0:
        err = remote.error_text(proc)
        if "can't find session" in err or "no server running" in err or "error connecting" in err:
            raise SessionError(f"`{name}` is not running")
        log.error("couldn't stop %s (rc=%s): %s", name, proc.returncode, remote.full_error(proc))
        raise SessionError(f"couldn't stop `{name}`: {err}")


# ---------------------------------------------------------------- attach

def attach_argv(cfg: Config, name: str) -> List[str]:
    s = cfg.session(name)
    return remote.wrap(cfg.host_of(s), TMUX + ["attach", "-t", target(name)], tty=True)


def attach(cfg: Config, name: str) -> int:
    """Attach in the foreground until detached, then mark the session seen."""
    s = cfg.session(name)
    log.info("attaching to %s on %s", name, s.host)
    # undo a preview fit() so the window follows the attaching terminal again. Separate
    # and best-effort: tmux < 2.9 has no window-size, and a failing command in a `;`
    # chain would stop the attach.
    remote.run(cfg.host_of(s), TMUX + ["set-option", "-w", "-u", "-t", target(name),
                                       "window-size"])
    code = remote.interactive(cfg.host_of(s), TMUX + ["attach", "-t", target(name)])
    log.info("back from %s (exit %s)", name, code)
    mark_seen(cfg, name)
    return code


def mark_seen(cfg: Config, name: str) -> None:
    s = cfg.session(name)
    proc = remote.python(cfg.host_of(s), MARK_SEEN, name)
    if proc.returncode != 0:
        log.warning("couldn't mark %s as seen: %s", name, remote.full_error(proc))


def forget(cfg: Config, name: str) -> None:
    """Delete a removed session's files on its host, so re-adding the name starts clean."""
    s = cfg.session(name)
    files = " ".join(f'"$HOME/.derot/{d}/"{shlex.quote(name + ext)}'
                     for d, ext in (("state", ".json"), ("env", ".sh")))
    proc = remote.sh(cfg.host_of(s), f"rm -f {files}")
    if proc.returncode != 0:
        log.warning("couldn't clean up %s on %s: %s", name, s.host, remote.full_error(proc))


def mark_answered(cfg: Config, name: str, seen_ts: float) -> None:
    """waiting -> busy after you answered the prompt from derot (see MARK_ANSWERED)."""
    proc = remote.python(cfg.host_of(cfg.session(name)), MARK_ANSWERED, name, repr(seen_ts))
    if proc.returncode != 0:
        log.warning("couldn't mark %s as answered: %s", name, remote.full_error(proc))


def login(cfg: Config, account_name: str, host_name: str = "local") -> int:
    if account_name not in cfg.accounts:
        raise SessionError(f"unknown account '{account_name}'")
    if host_name not in cfg.hosts:
        raise SessionError(f"unknown host '{host_name}'")
    host, account = cfg.hosts[host_name], cfg.accounts[account_name]
    command = _cmd(host.codex) + " login" if account.agent == "codex" else _cmd(host.claude)
    inner = "\n".join([*env_lines(account, "_login"), 'cd "$HOME"', command])
    proc = remote.sh(host, write_env_script("_login") + " && "
                     + write_run_script("_login", inner), input=env_content(account))
    if proc.returncode != 0:
        raise SessionError(f"couldn't prepare login on {host_name}: {remote.error_text(proc)}")
    log.info("opening login for account %s on %s", account_name, host_name)
    return remote.interactive(host, ["sh", "-c", launch_cmd("_login")])


# ---------------------------------------------------------------- past conversations

# Lists a folder's past conversations from Claude Code's transcripts:
# <config dir>/projects/<folder, non-alphanumerics as ->/<conversation id>.jsonl.
# Titles are found by searching backwards (transcripts get big), the first prompt from the top.
CONVERSATIONS_SCRIPT = r"""
import glob, json, mmap, os, re, sys
cdir, folder, limit = os.path.expanduser(sys.argv[1]), os.path.expanduser(sys.argv[2]), int(sys.argv[3])
folders = set(re.sub(r"[^A-Za-z0-9]", "-", p)
              for p in (os.path.realpath(folder), os.path.abspath(folder)))
files = []
for f in folders:
    files += glob.glob(os.path.join(cdir, "projects", glob.escape(f), "*.jsonl"))
files = sorted(set(files), key=lambda p: -os.path.getmtime(p))

def entry_at(m, i):
    start, end = m.rfind(b"\n", 0, i) + 1, m.find(b"\n", i)
    try:
        return json.loads(m[start:end if end != -1 else len(m)].decode("utf-8", "replace"))
    except ValueError:
        return {}

def last(m, kind, key):
    # Claude writes compact JSON; also accept "type": "x"
    i = max(m.rfind(b'"type":"%s"' % kind), m.rfind(b'"type": "%s"' % kind))
    return str(entry_at(m, i).get(key) or "") if i != -1 else ""

def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                return b.get("text") or ""
    return ""

def first_prompt(m):
    pos = 0
    while pos < min(len(m), 1 << 20):
        end = m.find(b"\n", pos)
        end = len(m) if end == -1 else end
        line = m[pos:end]
        pos = end + 1
        if b'"user"' not in line:
            continue
        try:
            e = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            continue
        if e.get("type") != "user" or e.get("isMeta") or e.get("isSidechain"):
            continue
        t = text_of((e.get("message") or {}).get("content")).strip()
        if t and not t.startswith(("<", "[Request interrupted")):
            return t
    return ""

out = []
for path in files:
    if len(out) >= limit:
        break
    try:
        with open(path, "rb") as fh:
            if os.fstat(fh.fileno()).st_size == 0:
                continue
            m = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
            first = first_prompt(m)
            if not first:
                continue  # nothing was said: not worth resuming
            out.append({
                "id": os.path.basename(path)[:-len(".jsonl")],
                "mtime": os.path.getmtime(path),
                "title": last(m, b"custom-title", "customTitle")
                         or last(m, b"ai-title", "aiTitle"),
                "first": first,
                "last": last(m, b"last-prompt", "lastPrompt"),
            })
    except Exception:
        continue
print(json.dumps(out))
"""


# Codex: <CODEX_HOME>/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl, the folder in the
# first line's session_meta.cwd, titles in session_index.jsonl (id, thread_name).
CODEX_CONVERSATIONS_SCRIPT = r"""
import glob, json, os, sys
cdir, folder, limit = os.path.expanduser(sys.argv[1]), os.path.expanduser(sys.argv[2]), int(sys.argv[3])
roots = {os.path.realpath(folder), os.path.abspath(folder)}
titles = {}
try:
    with open(os.path.join(cdir, "session_index.jsonl"), errors="replace") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("id") and e.get("thread_name"):
                titles[str(e["id"])] = str(e["thread_name"])
except OSError:
    pass

def user_texts(lines):
    for line in lines:
        if b'"user"' not in line:
            continue
        try:
            e = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            continue
        p = e.get("payload") if isinstance(e, dict) else None
        if not isinstance(p, dict) or p.get("type") != "message" or p.get("role") != "user":
            continue
        for b in p.get("content") or []:
            t = (b.get("text") if isinstance(b, dict) else "") or ""
            if t.strip() and not t.lstrip().startswith(("<", "# AGENTS.md")):
                yield t.strip()

files = glob.glob(os.path.join(cdir, "sessions", "*", "*", "*", "rollout-*.jsonl"))
files = sorted(files, key=lambda p: -os.path.getmtime(p))[:3000]
out = []
for path in files:
    if len(out) >= limit:
        break
    try:
        with open(path, "rb") as fh:
            meta = json.loads(fh.readline().decode("utf-8", "replace"))
            payload = meta.get("payload") or {}
            cwd = payload.get("cwd") or ""
            if not cwd or os.path.realpath(cwd) not in roots:
                continue
            head = fh.read(1 << 20)
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - (256 << 10)))
            tail = fh.read()
    except Exception:
        continue
    first = next(user_texts(head.splitlines()), "")
    if not first:
        continue  # nothing was said: not worth resuming
    lasts = list(user_texts(tail.splitlines()))
    conv = str(payload.get("id") or os.path.basename(path)[-41:-6])
    out.append({"id": conv, "mtime": os.path.getmtime(path), "title": titles.get(conv, ""),
                "first": first, "last": lasts[-1] if lasts else first})
print(json.dumps(out))
"""


@dataclass
class Conversation:
    id: str
    mtime: float
    title: str = ""
    first: str = ""
    last: str = ""


def conversations(cfg: Config, name: str, limit: int = 40) -> List[Conversation]:
    """Past conversations in the session's folder for its account, newest first."""
    s = cfg.session(name)
    account = cfg.account_of(s)
    script = CODEX_CONVERSATIONS_SCRIPT if account.agent == "codex" else CONVERSATIONS_SCRIPT
    proc = remote.python(cfg.host_of(s), script, account.config_dir, s.dir, str(limit),
                         timeout=30)
    if proc.returncode != 0:
        log.error("couldn't list conversations of %s: %s", name, remote.full_error(proc))
        raise SessionError(f"couldn't list conversations of `{name}`: {remote.error_text(proc)}")
    try:
        items = json.loads(remote.last_line(proc.stdout) or "[]")
    except ValueError:
        raise SessionError(f"couldn't read the conversations of `{name}`")
    return [Conversation(str(i["id"]), float(i["mtime"]), str(i.get("title") or ""),
                         str(i.get("first") or ""), str(i.get("last") or ""))
            for i in items if isinstance(i, dict) and i.get("id")]


# ---------------------------------------------------------------- preview / typing

CONVERSATION_SCRIPT = r"""
import json, os, sys
path, limit = os.path.expanduser(sys.argv[1]), int(sys.argv[2])
try:
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        f.seek(max(0, f.tell() - 400 * 1024))
        data = f.read()
except FileNotFoundError:
    print(json.dumps({"items": []}))  # Claude creates it with the first message
    sys.exit(0)
except OSError as e:
    print(json.dumps({"error": str(e)}))
    sys.exit(0)

def summary(name, inp):
    if isinstance(inp, dict):
        for k in ("command", "file_path", "url", "pattern", "description", "prompt"):
            if inp.get(k):
                return "%s: %s" % (name, " ".join(str(inp[k]).split())[:160])
    return str(name)

items = []
def add(role, text):
    text = (text or "").strip()
    if not text:
        return
    if items and items[-1]["role"] == role and role in ("you", "claude"):
        items[-1]["text"] += "\n\n" + text
    else:
        items.append({"role": role, "text": text})

for raw in data.splitlines():
    try:
        e = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        continue
    if not isinstance(e, dict) or e.get("isSidechain") or e.get("isMeta"):
        continue
    kind, msg = e.get("type"), e.get("message") or {}
    content = msg.get("content") if isinstance(msg, dict) else None
    if kind == "user":
        if isinstance(content, str):
            if not content.lstrip().startswith("<"):  # skip injected command/system text
                add("you", content)
            continue
        for b in content if isinstance(content, list) else []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                t = b.get("text") or ""
                if t.startswith("[Request interrupted by user"):
                    add("note", "interrupted")
                elif not t.lstrip().startswith("<"):
                    add("you", t)
            elif b.get("type") == "tool_result" and b.get("is_error"):
                c = b.get("content")
                c = c if isinstance(c, str) else json.dumps(c)
                add("note", "declined" if "doesn't want to proceed" in c else
                    "error: " + c.strip().splitlines()[0][:200] if c.strip() else "error")
    elif kind == "assistant":
        for b in content if isinstance(content, list) else [{"type": "text", "text": content}]:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                add("claude", b.get("text"))
            elif b.get("type") == "tool_use":
                add("tool", summary(b.get("name") or "tool", b.get("input")))
    elif kind == "response_item" and isinstance(e.get("payload"), dict):  # Codex rollout
        p = e["payload"]
        if p.get("type") == "message" and p.get("role") in ("user", "assistant"):
            for b in p.get("content") or []:
                t = b.get("text") if isinstance(b, dict) else None
                if not t:
                    continue
                if p["role"] == "assistant":
                    add("claude", t)
                elif not t.lstrip().startswith(("<", "# AGENTS.md")):  # injected context
                    add("you", t)
        elif p.get("type") in ("function_call", "custom_tool_call", "local_shell_call"):
            args = p.get("arguments") or p.get("input") or p.get("action")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {"command": args}
            add("tool", summary(p.get("name") or "tool", args))
    elif kind == "event_msg" and isinstance(e.get("payload"), dict) \
            and e["payload"].get("type") == "turn_aborted":
        add("note", "interrupted")

items = items[-limit:]
for it in items:
    if len(it["text"]) > 4000:
        it["text"] = it["text"][:4000] + "…"
print(json.dumps({"items": items}))
"""


def conversation(cfg: Config, name: str, transcript: str, limit: int = 40) -> List[dict]:
    """Recent conversation items [{role: you|claude|tool|note, text}] from the transcript."""
    if not transcript:
        return []
    proc = remote.python(cfg.host_of(cfg.session(name)), CONVERSATION_SCRIPT, transcript,
                         str(limit), timeout=10)
    try:
        data = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise SessionError(f"couldn't read the conversation: {remote.error_text(proc)}")
    if "error" in data:
        raise SessionError(f"couldn't read the conversation: {data['error']}")
    return data.get("items", [])


def fit(cfg: Config, name: str, width: int, height: int) -> bool:
    """Resize a session nobody is attached to, so Claude lays out its UI for the preview.

    This makes the window size "manual"; attach() hands sizing back to the terminal.
    """
    width, height = max(40, width), max(10, height)
    proc = remote.run(cfg.host_of(cfg.session(name)),
                      TMUX + ["resize-window", "-t", target(name), "-x", str(width),
                              "-y", str(height)], timeout=10)
    if proc.returncode != 0:
        log.warning("couldn't resize %s for the preview: %s", name, remote.full_error(proc))
    return proc.returncode == 0


@dataclass
class Screen:
    text: str  # visible screen with colours/styles (ANSI)
    size: Optional[Tuple[int, int]] = None  # window width, height
    cursor: Optional[Tuple[int, int]] = None  # x, y within the visible screen


def screen(cfg: Config, name: str) -> Screen:
    """What you'd see when attached: the visible screen, its size and the cursor."""
    proc = remote.run(cfg.host_of(cfg.session(name)), TMUX + [
        "display-message", "-p", "-t", target(name),
        "#{window_width} #{window_height} #{cursor_x} #{cursor_y}", ";",
        "capture-pane", "-p", "-e", "-t", target(name)], timeout=10)
    if proc.returncode != 0:
        raise SessionError(f"couldn't read the screen: {remote.error_text(proc)}")
    first, _, text = proc.stdout.partition("\n")
    try:
        w, h, x, y = (int(v) for v in first.split())
    except ValueError:
        return Screen(proc.stdout.rstrip("\n"))
    return Screen(text.rstrip("\n"), (w, h), (x, y))


# Textual key names -> tmux key names (printable characters are sent literally)
TMUX_KEYS = {
    "enter": "Enter", "escape": "Escape", "tab": "Tab", "shift+tab": "BTab",
    "backspace": "BSpace", "delete": "DC", "up": "Up", "down": "Down", "left": "Left",
    "right": "Right", "home": "Home", "end": "End", "pageup": "PPage", "pagedown": "NPage",
    "insert": "IC", "space": "Space",
}


# Textual names for punctuation that only arrives with a modifier (ctrl+_ and friends)
PUNCT_KEYS = {"underscore": "_", "minus": "-", "slash": "/", "backslash": "\\",
              "at": "@", "space": "Space", "left_square_bracket": "[",
              "right_square_bracket": "]", "circumflex_accent": "^"}
MODIFIERS = {"ctrl": "C-", "alt": "M-", "shift": "S-"}


def tmux_key(key: str) -> Optional[str]:
    """tmux name for a Textual key name, or None if it isn't forwarded."""
    if key in TMUX_KEYS:
        return TMUX_KEYS[key]
    if key in ("shift+enter", "alt+enter"):
        return "M-Enter"  # a newline in Claude's prompt (plain S-Enter would submit)
    *mods, base = key.split("+")
    if base in TMUX_KEYS:
        base = TMUX_KEYS[base]
    elif base in PUNCT_KEYS:
        base = PUNCT_KEYS[base]
    elif base[:1] == "f" and base[1:].isdigit():
        base = base.upper()
    elif len(base) != 1:
        return None
    if not mods:
        return base
    if any(m not in MODIFIERS for m in mods):
        return None
    return "".join(MODIFIERS[m] for m in mods) + base


def _literal(text: str) -> List[str]:
    """Arguments that tmux passes through as exactly `text`.

    tmux reads an argument ending in ";" as a command separator (and "\\;" as an escaped
    ";", eating the backslash), so trailing semicolons go as separate "\\;" arguments.
    """
    base = text.rstrip(";")
    return ([base] if base else []) + ["\\;"] * (len(text) - len(base))


PASTE_BUFFER = "derot-paste"


def _input_argv(name: str, chunks: List[Tuple[str, str]]) -> List[str]:
    argv: List[str] = []
    for kind, value in chunks:
        if not value:
            continue
        if argv:
            argv.append(";")
        if kind == "text":
            argv += ["send-keys", "-t", target(name), "-l", "--"] + _literal(value)
        elif kind == "paste":
            # one block (bracketed paste when the app asks for it, as Claude does), so a
            # multi-line paste isn't submitted line by line
            for i, part in enumerate(_literal(value)):
                argv += ["set-buffer"] + (["-a"] if i else []) + [
                    "-b", PASTE_BUFFER, "--", part, ";"]
            argv += ["paste-buffer", "-p", "-d", "-b", PASTE_BUFFER, "-t", target(name)]
        else:
            argv += ["send-keys", "-t", target(name), value]
    return argv


KEY_AFTER_TEXT_GAP = 0.05


def _bursts(chunks: List[Tuple[str, str]]) -> List[List[Tuple[str, str]]]:
    """Split before a key that follows text: Claude Code reads a long burst of text as a
    paste and swallows an Enter that arrives with it (seen on 2.1.316: 81 characters and
    Enter in one write didn't submit; 30 ms apart did)."""
    out: List[List[Tuple[str, str]]] = [[]]
    for kind, value in chunks:
        if kind == "key" and out[-1] and out[-1][-1][0] in ("text", "paste"):
            out.append([])
        out[-1].append((kind, value))
    return [b for b in out if b]


def send_input(cfg: Config, name: str, chunks: List[Tuple[str, str]]) -> None:
    """Send input in order: ("text", "abc") literally, ("paste", "...") as one pasted
    block, ("key", "Enter") as a key.

    One tmux call per burst, so fast typing doesn't mean one SSH call per key; a key right
    after text goes in its own call, a moment later (see _bursts).
    """
    host = cfg.host_of(cfg.session(name))
    for i, burst in enumerate(_bursts(chunks)):
        argv = _input_argv(name, burst)
        if not argv:
            continue
        if i:
            time.sleep(KEY_AFTER_TEXT_GAP)
        proc = remote.run(host, TMUX + argv)
        if proc.returncode != 0:
            log.error("couldn't type into %s: %s", name, remote.full_error(proc))
            raise SessionError(f"couldn't type into `{name}`: {remote.error_text(proc)}")


def paste(cfg: Config, name: str, text: str) -> None:
    send_input(cfg, name, [("paste", text)])


def send_key(cfg: Config, name: str, key: str) -> None:
    """Press one key in the session, e.g. "1" to pick an option in a prompt."""
    s = cfg.session(name)
    log.info("sending key %s to %s", key, name)
    proc = remote.run(cfg.host_of(s), TMUX + ["send-keys", "-t", target(name), key])
    if proc.returncode != 0:
        raise SessionError(f"couldn't send to `{name}`: {remote.error_text(proc)}")


# ---------------------------------------------------------------- display helpers

def age(ts: float, now: Optional[float] = None) -> str:
    if not ts:
        return ""
    secs = max(0, int((now or time.time()) - ts))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def status_text(st: Status, now: Optional[float] = None) -> str:
    label = STYLE[st.state][1]
    a = age(st.ts, now) if st.state not in ("offline",) else ""
    return f"{label} · {a}" if a else label


def happening(st: Status) -> str:
    if st.state in ("waiting", "done", "offline"):
        return st.message
    if st.state == "busy":
        parts = []
        if st.prompt:
            parts.append(f"“{st.prompt}”")
        if st.message:
            parts.append(st.message)
        return " — ".join(parts)
    if st.message == HOOK_MISSING:
        return st.message
    if st.sdef.note:
        return st.sdef.note
    return f"last: “{st.prompt}”" if st.prompt else ""
