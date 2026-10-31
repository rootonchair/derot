"""Desktop notifications on session state transitions."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .config import Notify
from .log import log
from .sessions import Status

MAX_BODY = 90  # a glance, not the whole reply; the console shows the rest


def brief(text: str, limit: int = MAX_BODY) -> str:
    """First sentence of text, at most `limit` characters, cut at a word boundary."""
    text = " ".join((text or "").split())
    # "wants to use Bash: rm -rf build": the part after the colon is the point
    ends = (". ", "! ", "? ") if text.startswith("wants to use ") else (". ", "! ", "? ", ": ")
    for end in ends:
        i = text.find(end)
        if 0 < i < limit:
            text = text[: i + 1].rstrip(":")
            break
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0] or text[: limit - 1]
    return cut.rstrip(",;:-") + "…"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def send(title: str, body: str, sound: str = "") -> None:
    """Fire-and-forget desktop notification."""
    body = brief(body)
    try:
        if sys.platform == "darwin" and shutil.which("osascript"):
            script = f'display notification "{_esc(body)}" with title "{_esc(title)}"'
            if sound:
                script += f' sound name "{_esc(sound)}"'
            subprocess.Popen(["osascript", "-e", script],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif shutil.which("notify-send"):
            subprocess.Popen(["notify-send", title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            sys.stderr.write("\a")
            sys.stderr.flush()
    except OSError as e:
        log.warning("couldn't send desktop notification: %s", e)


def watch_lock() -> Path:
    return Path("~/.ccdeck/watch.pid").expanduser()


# The lock is an flock on ~/.ccdeck/watch.pid, held for the life of `ccdeck watch`: taking
# it is atomic, and the kernel drops it however the process ends (even SIGKILL), so a
# crashed watch never leaves alerts silently deferred to nobody.
_watch_fd: Optional[int] = None


def watch_running() -> bool:
    """True if another process holds the `ccdeck watch` lock."""
    if _watch_fd is not None:
        return False  # that's us
    try:
        fd = os.open(watch_lock(), os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)  # also releases a lock taken just now


def acquire_watch_lock() -> bool:
    """Become the one desktop notifier. False if another `ccdeck watch` is running."""
    global _watch_fd
    if _watch_fd is not None:
        return True
    path = watch_lock()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())  # for people looking at the file
    _watch_fd = fd
    return True


def release_watch_lock() -> None:
    global _watch_fd
    if _watch_fd is not None:
        os.close(_watch_fd)
        _watch_fd = None


class Notifier:
    """Remembers each session's last state and alerts on transitions after the first poll.

    - no alert for a session someone is attached to (they're looking at it)
    - `offline` doesn't count as a state: when a host comes back, sessions are compared with
      what they were before it dropped, so nothing is re-announced
    - with defer_to_watch (the console), desktop alerts are left to a running `ccdeck watch`
      so they aren't sent twice; the console still shows its toast
    """

    def __init__(self, settings: Notify, toast: Optional[Callable[[str, str], None]] = None,
                 defer_to_watch: bool = False):
        self.settings = settings
        self.toast = toast
        self.defer_to_watch = defer_to_watch
        self.last: Dict[str, Tuple[str, int]] = {}  # name -> (state, hook alert count)
        self.primed = False

    def update(self, statuses: Iterable[Status]) -> List[Tuple[str, str]]:
        """Process a poll result; returns the (title, body) alerts that were sent."""
        sent: List[Tuple[str, str]] = []
        current = {st.name: st for st in statuses}
        if self.primed:
            desktop = not (self.defer_to_watch and watch_running())
            for name, st in current.items():
                prev = self.last.get(name)
                # prev None: first time seen online (host was down at start, or new in the
                # config) - that's the baseline, not a change
                if prev is None or st.state == "offline" or st.attached:
                    continue
                prev_state, prev_alerts = prev
                # same state but the hook counted a new prompt / reply since the last poll
                # (approve, Claude runs a quick tool, asks again within one refresh)
                repeat = prev_state == st.state and st.alerts > prev_alerts
                if prev_state == st.state and not repeat:
                    continue
                alert = self._alert(st, prev_state, repeat)
                if alert:
                    sent.append(alert)
                    log.info("alert: %s: %s%s", alert[0], alert[1],
                             "" if desktop else " (desktop alert left to ccdeck watch)")
                    if desktop:
                        send(alert[0], alert[1], self.settings.sound)
                    if self.toast:
                        self.toast(*alert)
        self.last = {
            name: (self.last.get(name) if st.state == "offline" else (st.state, st.alerts))
            for name, st in current.items()
        }
        self.primed = True
        return sent

    def _alert(self, st: Status, prev: Optional[str],
               repeat: bool = False) -> Optional[Tuple[str, str]]:
        if st.state == "waiting" and self.settings.on_waiting:
            return f"{st.name} needs you", brief(st.message or "waiting for you")
        if st.state == "done" and (repeat or prev in ("busy", "waiting", "idle")) \
                and self.settings.on_done:
            return f"{st.name} finished", brief(st.message or "finished")
        return None
