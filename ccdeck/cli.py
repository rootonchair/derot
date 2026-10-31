"""ccdeck command-line entry point."""

from __future__ import annotations

import argparse
import sys
import time
from typing import List, Optional

from . import __version__
from . import config as config_mod
from . import log as log_mod
from .config import ConfigError
from .log import log


def _load(create: bool = False):
    path = config_mod.config_path()
    created = config_mod.ensure_config(path) if create else False
    return config_mod.load(path), created


def _hex_to_ansi(color: str, text: str, bold: bool) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"\033[{'1;' if bold else ''}38;2;{r};{g};{b}m{text}\033[0m"


def cmd_tui(args) -> int:
    cfg, created = _load(create=True)
    if created:
        print(f"Created a starter config at {cfg.path}")
    from . import tui
    tui.run(cfg, created=created)
    return 0


def cmd_init(args) -> int:
    path = config_mod.config_path()
    if config_mod.ensure_config(path):
        print(f"Created {path}")
        print("Next: edit it, then run `ccdeck login ACCOUNT` and `ccdeck setup`.")
    else:
        print(f"{path} already exists")
    return 0


def cmd_setup(args) -> int:
    from . import installer
    cfg, _ = _load()
    return installer.setup(cfg, remove=args.remove)


def cmd_ls(args) -> int:
    from . import sessions
    from .notify import brief
    from .sessions import STYLE
    cfg, _ = _load()
    statuses, offline = sessions.poll_full(cfg)
    if not statuses:
        print(f"no sessions yet — add some to {cfg.path}")
        return 0
    color = sys.stdout.isatty()
    now = time.time()
    rows = []
    for st in statuses:
        icon, _, hexcolor, bold = STYLE[st.state]
        name = st.name + (" ◂" if st.attached else "")
        rows.append((icon, name, st.account.name, st.host.name,
                     sessions.status_text(st, now), brief(sessions.happening(st), 100),
                     hexcolor, bold))
    headers = ("", "SESSION", "ACCOUNT", "MACHINE", "STATUS", "WHAT'S HAPPENING")
    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(5)]

    def line(cells, hexcolor=None, bold=False) -> str:
        parts = [cells[i].ljust(widths[i]) for i in range(5)] + [cells[5]]
        if color and hexcolor:
            parts[0] = _hex_to_ansi(hexcolor, parts[0], bold)
            parts[4] = _hex_to_ansi(hexcolor, parts[4], bold)
        return "  ".join(parts).rstrip()

    print(line(headers))
    for r in rows:
        print(line(r[:6], r[6], r[7]))
    for host, err in offline.items():
        print(f"✗ can't reach {host}: {err}", file=sys.stderr)
    return 0


def cmd_start(args) -> int:
    from . import installer, sessions
    cfg, _ = _load()
    cfg.session(args.name)
    try:
        s = cfg.session(args.name)
        if not installer.ensure_hooks(cfg, cfg.host_of(s), cfg.account_of(s).config_dir):
            print(f"ccdeck: status hooks for {s.account} on {s.host} couldn't be set up "
                  "(see `ccdeck log`)", file=sys.stderr)
        sessions.start(cfg, args.name, cont=args.cont, resume=args.resume or "")
    except sessions.SessionError as e:
        print(f"ccdeck: {e}", file=sys.stderr)
        return 1
    if args.detach:
        print(f"started {args.name}")
        return 0
    return sessions.attach(cfg, args.name)


def cmd_history(args) -> int:
    from . import sessions
    cfg, _ = _load()
    cfg.session(args.name)
    try:
        items = sessions.conversations(cfg, args.name, limit=args.n)
    except sessions.SessionError as e:
        print(f"ccdeck: {e}", file=sys.stderr)
        return 1
    if not items:
        print(f"no past conversations for {args.name}")
    for c in items:
        print(f"{c.id}  {sessions.age(c.mtime):>4} ago  {' '.join((c.title or c.first).split())[:70]}")
    return 0


def cmd_attach(args) -> int:
    from . import sessions
    cfg, _ = _load()
    cfg.session(args.name)
    return sessions.attach(cfg, args.name)


def cmd_stop(args) -> int:
    from . import sessions
    cfg, _ = _load()
    cfg.session(args.name)
    try:
        sessions.stop(cfg, args.name)
    except sessions.SessionError as e:
        print(f"ccdeck: {e}", file=sys.stderr)
        return 1
    print(f"stopped {args.name}")
    return 0


def cmd_watch(args) -> int:
    from . import sessions
    from .notify import Notifier
    from .notify import acquire_watch_lock
    cfg, _ = _load()
    if not acquire_watch_lock():
        print("ccdeck watch is already running", file=sys.stderr)
        return 1
    notifier = Notifier(cfg.notify)
    print(f"watching {len(cfg.sessions)} session(s) every {cfg.refresh:g}s — Ctrl-C to stop")
    mtime = _mtime(cfg.path)
    try:
        while True:
            m = _mtime(cfg.path)
            if m != mtime:
                mtime = m
                try:
                    cfg = config_mod.load(cfg.path)
                    notifier.settings = cfg.notify
                    print("config reloaded")
                except ConfigError as e:
                    log.error("watch: config not reloaded: %s", e)
                    print(f"config not reloaded: {e}", file=sys.stderr)
            try:
                statuses = sessions.poll(cfg)
                for title, body in notifier.update(statuses):
                    print(f"{time.strftime('%H:%M:%S')}  {title}: {body}", flush=True)
            except Exception as e:  # keep watching; logged too (a service's stderr is unread)
                log.error("watch: poll failed: %s", e, exc_info=e)
                print(f"poll failed: {e}", file=sys.stderr)
            time.sleep(cfg.refresh)
    except KeyboardInterrupt:
        return 0


def _mtime(path) -> float:
    try:
        return path.stat().st_mtime if path else 0.0
    except OSError:
        return 0.0


def cmd_log(args) -> int:
    path = log_mod.log_path()
    if args.follow:
        import subprocess
        try:
            return subprocess.call(["tail", "-n", str(args.lines), "-F", str(path)])
        except KeyboardInterrupt:
            return 0
    text = log_mod.tail(args.lines)
    print(text if text else "(empty)")
    print(f"\n— {path}   (ccdeck log -f to follow; CCDECK_DEBUG=1 logs every command)",
          file=sys.stderr)
    return 0


def cmd_login(args) -> int:
    from . import sessions
    cfg, _ = _load()
    try:
        return sessions.login(cfg, args.account, args.host)
    except sessions.SessionError as e:
        print(f"ccdeck: {e}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ccdeck",
        description="One console for every Claude Code session, across projects, "
                    "accounts and machines.",
    )
    p.add_argument("--version", action="version", version=f"ccdeck {__version__}")
    p.set_defaults(func=cmd_tui)
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    sub.add_parser("init", help="create the config file").set_defaults(func=cmd_init)

    sp = sub.add_parser("setup", help="install / remove status hooks on every host+account")
    sp.add_argument("--remove", action="store_true", help="remove the hooks instead")
    sp.set_defaults(func=cmd_setup)

    sub.add_parser("ls", help="print a status table").set_defaults(func=cmd_ls)

    sp = sub.add_parser("start", help="start a session and attach to it")
    sp.add_argument("name")
    sp.add_argument("-c", "--continue", dest="cont", action="store_true",
                    help="resume the last conversation in that folder")
    sp.add_argument("-r", "--resume", metavar="ID",
                    help="resume that conversation (ids from `ccdeck history NAME`)")
    sp.add_argument("-d", "--detach", action="store_true", help="don't attach")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("history", help="list a session's past conversations (newest first)")
    sp.add_argument("name")
    sp.add_argument("-n", type=int, default=20, help="how many (default 20)")
    sp.set_defaults(func=cmd_history)

    sp = sub.add_parser("attach", help="attach to a running session")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_attach)

    sp = sub.add_parser("stop", help="stop a session")
    sp.add_argument("name")
    sp.set_defaults(func=cmd_stop)

    sub.add_parser("watch", help="poll and send notifications without the console"
                   ).set_defaults(func=cmd_watch)

    sp = sub.add_parser("log", help="show the log (~/.ccdeck/ccdeck.log), for tracing errors")
    sp.add_argument("-n", "--lines", type=int, default=60, help="how many lines (default 60)")
    sp.add_argument("-f", "--follow", action="store_true", help="keep printing new lines")
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("login", help="open Claude Code with an account's config so you can /login")
    sp.add_argument("account")
    sp.add_argument("--host", default="local")
    sp.set_defaults(func=cmd_login)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    log_mod.setup()
    if args.func is not cmd_log:
        log.debug("ccdeck %s", " ".join(sys.argv[1:] if argv is None else argv))
    try:
        return int(args.func(args) or 0)
    except ConfigError as e:
        log.error("config error: %s", e)
        print(f"ccdeck: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as e:
        log.critical("unexpected error in `ccdeck %s`", args.command or "", exc_info=e)
        print(f"ccdeck: unexpected error: {e}\n(full traceback in {log_mod.log_path()})",
              file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
