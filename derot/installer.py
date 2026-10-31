"""`derot setup [--remove]`: install the status hook and merge it into each account's
settings (Claude Code: settings.json; Codex: hooks.json)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable, Dict, List, Set, Tuple

from . import remote
from .config import Account, Config, Host
from .log import log

EVENTS = [
    "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse",
    "Notification", "Stop", "SessionEnd",
]
# Newer Claude Code events that make status more accurate (permission prompts, Esc
# interrupts, API errors). Only registered where that host's Claude Code knows them, since
# older versions may reject unknown event names in settings.json.
EXTRA_EVENTS = ["PermissionRequest", "PostToolUseFailure", "StopFailure"]
TOOL_EVENTS = ("PreToolUse", "PostToolUse", "PermissionRequest", "PostToolUseFailure")
# Codex's hooks (developers.openai.com/codex/hooks): same shape and names, no Notification,
# plus Interrupt. Codex only runs them after you approve them once in its /hooks screen.
CODEX_EVENTS = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest",
                "PostToolUse", "Stop", "Interrupt", "SessionEnd"]
SETTINGS_FILE = {"claude": "settings.json", "codex": "hooks.json"}

CHECK_SCRIPT = r"""
uname -s
for t in tmux python3; do
  if command -v "$t" >/dev/null 2>&1; then echo "$t=yes"; else echo "$t=no"; fi
done
# the login shell only prints its environment (works in fish/csh too); sh does the rest
lp=$("${SHELL:-/bin/sh}" -lic env </dev/null 2>/dev/null | grep '^PATH=' | tail -n 1)
find_cmd() {
  c=$1; case $c in "~/"*) c=$HOME/${c#"~/"};; esac
  ([ -n "$lp" ] && PATH=${lp#PATH=}; command -v "$c" 2>/dev/null | tail -n 1)
}
if [ -n "$2" ]; then
  if [ -n "$(find_cmd "$2")" ]; then echo "codex=yes"; else echo "codex=no"; fi
fi
[ -n "$1" ] || { echo "@@END"; exit 0; }
p=$(find_cmd "$1")
if [ -n "$p" ]; then
  echo "claude=yes"
  python3 - "$p" <<'PY' 2>/dev/null
import mmap, os, sys
names = ("PermissionRequest", "PostToolUseFailure", "StopFailure")
try:
    with open(os.path.realpath(sys.argv[1]), "rb") as f:
        m = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        print("events=" + ",".join(n for n in names if m.find(b'"%s"' % n.encode()) != -1))
except Exception:
    pass
PY
else
  echo "claude=no"
fi
echo "@@END"
"""

# written next to it, then renamed: an interrupted upload never leaves a cut-off hook.py
# (every hook call would fail, and the session would stay idle with no visible error)
UPLOAD_SCRIPT = (
    'mkdir -p "$HOME/.derot/state" && t="$HOME/.derot/.hook.py.$$" '
    '&& cat > "$t" && chmod 755 "$t" && mv -f "$t" "$HOME/.derot/hook.py" '
    '|| { rm -f "$t"; exit 1; }'
)

MERGE_SCRIPT = r"""
import json, os, shutil, sys, tempfile
cdir = os.path.expanduser(sys.argv[1])
mode = sys.argv[2]
events = [e for e in sys.argv[3].split(",") if e]
installing = set(e for e in sys.argv[4].split(",") if e) if len(sys.argv) > 4 else set(events)
tool_events = ("PreToolUse", "PostToolUse", "PermissionRequest", "PostToolUseFailure")
name = sys.argv[5] if len(sys.argv) > 5 else "settings.json"  # Codex: hooks.json
path = os.path.join(cdir, name)
shown = os.path.join(sys.argv[1], name)
MARK = "/.derot/hook.py"

if os.path.exists(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except Exception as e:
        print("%s is not valid JSON (%s); fix it first" % (shown, e))
        sys.exit(1)
    if not isinstance(data, dict):
        print("%s is not a JSON object; fix it first" % shown)
        sys.exit(1)
    bak = path + ".derot-bak"
    if not os.path.exists(bak):
        shutil.copy2(path, bak)
else:
    if mode == "remove":
        print("no %s, nothing to remove" % shown)
        sys.exit(0)
    os.makedirs(cdir, exist_ok=True)
    data = {}

hooks = data.get("hooks")
if hooks is None:
    hooks = {}
if not isinstance(hooks, dict):
    print("%s: 'hooks' is not an object; fix it first" % shown)
    sys.exit(1)

for ev in events:
    groups = hooks.get(ev)
    if not isinstance(groups, list):
        groups = [] if groups is None else [groups]
    kept_groups = []
    for g in groups:
        if isinstance(g, dict) and isinstance(g.get("hooks"), list):
            hs = g["hooks"]
            kept = [h for h in hs if not (isinstance(h, dict) and MARK in str(h.get("command", "")))]
            if len(kept) < len(hs):
                if not kept:
                    continue
                g = dict(g)
                g["hooks"] = kept
        kept_groups.append(g)
    if mode == "install" and ev in installing:
        group = {"hooks": [{"type": "command",
                            "command": "python3 ~/.derot/hook.py " + ev,
                            # Codex caps these two at 3 s; the hook takes milliseconds
                            "timeout": 3 if ev in ("SessionEnd", "Interrupt") else 10}]}
        if ev in tool_events:
            group = {"matcher": "*", "hooks": group["hooks"]}
        kept_groups.append(group)
    if kept_groups:
        hooks[ev] = kept_groups
    else:
        hooks.pop(ev, None)

if hooks:
    data["hooks"] = hooks
else:
    data.pop("hooks", None)

# write through a symlink (settings kept in a dotfiles repo) and keep the file's mode
real = os.path.realpath(path)
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(real), prefix=".settings-", suffix=".json")
with os.fdopen(fd, "w") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
if os.path.exists(real):
    os.chmod(tmp, os.stat(real).st_mode & 0o777)
os.replace(tmp, real)
print(("hooks added to " if mode == "install" else "hooks removed from ") + shown)
"""


def hook_source() -> str:
    return (Path(__file__).parent / "hook.py").read_text()


def _hint(tool: str, host: Host, is_mac: bool) -> str:
    if tool == "tmux":
        return "brew install tmux" if is_mac else "sudo apt install tmux"
    if tool == "python3":
        return "brew install python" if is_mac else "sudo apt install python3"
    if tool == "codex":
        return (f"install Codex there (npm install -g @openai/codex), or set `codex:` to its "
                f"full path for host '{host.name}'")
    return f"install Claude Code there, or set `claude:` to its full path for host '{host.name}'"


HOOKS_PRESENT_SCRIPT = r"""
import hashlib, os, re, sys
p = os.path.join(os.path.expanduser(sys.argv[1]), sys.argv[3] if len(sys.argv) > 3
                 else "settings.json")
events = [e for e in (sys.argv[4] if len(sys.argv) > 4 else "").split(",") if e]
try:
    with open(os.path.expanduser("~/.derot/hook.py"), "rb") as f:
        hook = hashlib.sha256(f.read()).hexdigest()
except Exception:
    hook = ""
try:
    with open(p) as f:
        wired = "/.derot/hook.py" in f.read()
except Exception:
    wired = False
answer = ("no hook.py" if not hook else "different hook.py" if hook != sys.argv[2]
          else "not in " + os.path.basename(p) if not wired else "yes")
if answer == "yes" and events:
    # Codex records each approved hook as [hooks.state."<hooks.json>:<event>:<i>:<j>"]
    try:
        with open(os.path.join(os.path.dirname(p), "config.toml")) as f:
            toml = f.read()
    except Exception:
        toml = ""
    snake = lambda e: re.sub(r"(?<!^)(?=[A-Z])", "_", e).lower()
    approved = all(re.search(r'\[hooks\.state\."%s:%s:' % (re.escape(p), snake(e)), toml)
                   for e in events)
    answer = "yes" if approved else "yes, not approved"
print(answer)
"""


def hook_hash() -> str:
    return hashlib.sha256(hook_source().encode()).hexdigest()


# (host, Codex folder) pairs whose hooks are installed but not approved in /hooks yet, from
# the last check; the poll uses it to tell "waiting for approval" from "no prompt yet"
CODEX_UNAPPROVED: Set[Tuple[str, str]] = set()


def hooks_present(host: Host, config_dir: str, agent: str = "claude") -> bool:
    """True if this version's hook script is on the host (not cut off, not an older one)
    and wired into that account folder's settings. A failed check counts as present:
    starting shouldn't depend on it. For Codex, also notes whether they're approved."""
    events = ",".join(CODEX_EVENTS) if agent == "codex" else ""
    proc = remote.python(host, HOOKS_PRESENT_SCRIPT, config_dir, hook_hash(),
                         SETTINGS_FILE[agent], events, timeout=15)
    if proc.returncode != 0:
        log.warning("couldn't check hooks on %s: %s", host.name, remote.full_error(proc))
        return True
    answer = remote.last_line(proc.stdout)
    if agent == "codex":
        if answer == "yes, not approved":
            CODEX_UNAPPROVED.add((host.name, config_dir))
        else:
            CODEX_UNAPPROVED.discard((host.name, config_dir))
    if not answer.startswith("yes"):
        log.info("hooks for %s on %s: %s", config_dir, host.name, answer or "no answer")
    return answer.startswith("yes")


def ensure_hooks(cfg: Config, host: Host, account: Account,
                 out: Callable[[str], None] = lambda line: None) -> bool:
    """Set up hooks on the host if that account folder doesn't have them (e.g. a setup
    that was interrupted). Returns False only if a needed setup failed."""
    if hooks_present(host, account.config_dir, account.agent):
        return True
    log.info("hooks missing for %s on %s: setting them up", account.config_dir, host.name)
    return setup_host(cfg, host, False, out)


def setup_host(cfg: Config, host: Host, remove: bool, out: Callable[[str], None]) -> bool:
    label = "this Mac" if host.is_local else host.ssh
    out(f"{host.name} ({label})")
    log.info("setup%s on %s (%s)", " --remove" if remove else "", host.name, label)
    ok = True

    def mark(good: bool, text: str, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        out(f"  {'✓' if good else '✗'} {text}")
        if good:
            log.info("setup %s: ✓ %s", host.name, text)
        else:
            log.error("setup %s: ✗ %s%s", host.name, text, f"\n{detail}" if detail else "")

    agents = {a.agent for a in cfg.accounts_on(host.name)} or {"claude"}
    if not remove:
        proc = remote.sh(host, CHECK_SCRIPT,
                         (host.claude.split() or ["claude"])[0] if "claude" in agents else "",
                         (host.codex.split() or ["codex"])[0] if "codex" in agents else "",
                         timeout=40)
        if proc.returncode != 0 or "@@END" not in proc.stdout:
            mark(False, f"can't reach it: {remote.error_text(proc)}", remote.full_error(proc))
            return False
        lines = proc.stdout.splitlines()
        is_mac = bool(lines) and lines[0].strip() == "Darwin"
        found: Dict[str, bool] = {}
        extras: List[str] = []
        for ln in lines:
            k, _, v = ln.strip().partition("=")
            if k == "events":
                extras = [e for e in EXTRA_EVENTS if e in v.split(",")]
            elif v:
                found[k] = v == "yes"
        for tool in ("tmux", "python3", *sorted(agents)):
            if found.get(tool):
                mark(True, f"{tool} ({host.command(tool)})" if tool in agents else tool)
            else:
                mark(False, f"{tool} not found → {_hint(tool, host, is_mac)}")
        if not found.get("python3"):
            out("  (skipping hook install: python3 is required)")
            return False

        proc = remote.sh(host, UPLOAD_SCRIPT, input=hook_source())
        if proc.returncode != 0:
            mark(False, f"couldn't install ~/.derot/hook.py: {remote.error_text(proc)}",
                 remote.full_error(proc))
            return False
        mark(True, "hook installed at ~/.derot/hook.py")
    else:
        probe = remote.sh(host, "echo ok")
        if probe.returncode != 0:
            mark(False, f"can't reach it: {remote.error_text(probe)}", remote.full_error(probe))
            return False

    mode = "remove" if remove else "install"
    every = EVENTS + EXTRA_EVENTS  # always clean all of them, so upgrades/downgrades work
    install = every if remove else EVENTS + extras
    if not remove:
        log.info("setup %s: extra events supported by its Claude Code: %s", host.name,
                 ", ".join(extras) or "none")
    for account in cfg.accounts_on(host.name):
        codex = account.agent == "codex"
        events = (CODEX_EVENTS, CODEX_EVENTS) if codex else (every, install)
        proc = remote.python(host, MERGE_SCRIPT, account.config_dir, mode, ",".join(events[0]),
                             ",".join(events[1]), SETTINGS_FILE[account.agent])
        msg = remote.last_line(proc.stdout) or remote.error_text(proc)
        mark(proc.returncode == 0, f"{account.name}: {msg}",
             "" if proc.returncode == 0 else remote.full_error(proc))
        if codex and not remove and proc.returncode == 0:
            out(f"  ! {account.name}: Codex runs new hooks only after you approve them: open a "
                "Codex session and trust them in /hooks (once per account folder)")
    return ok


def setup(cfg: Config, remove: bool = False, out: Callable[[str], None] = print) -> int:
    hosts = cfg.used_hosts()
    if not hosts:
        out("No sessions in the config yet, so there is nothing to set up.")
        out(f"Add sessions to {cfg.path or 'the config'} and run `derot setup` again.")
        return 0
    all_ok = True
    for host in hosts:
        all_ok = setup_host(cfg, host, remove, out) and all_ok
    out("")
    if all_ok:
        out("All done." if not remove else "Status hooks removed.")
    else:
        out("Some steps failed (✗ above). Fix them and run `derot setup` again.")
    return 0 if all_ok else 1
