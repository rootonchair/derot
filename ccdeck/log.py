"""Logging to ~/.ccdeck/ccdeck.log, so failures in background steps can be traced later.

Levels: INFO for actions (start, stop, setup, config saves), WARNING/ERROR for failures with
full stderr or tracebacks. Set CCDECK_DEBUG=1 to also log every command ccdeck runs.
"""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

log = logging.getLogger("ccdeck")
log.addHandler(logging.NullHandler())  # nothing reaches the terminal before setup()
log.propagate = False

SECRET_RE = re.compile(
    r"((?:[A-Za-z_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Za-z_]*)=)('[^']*'|\"[^\"]*\"|\S+)"
    r"|sk-ant-[A-Za-z0-9_-]+",
    re.IGNORECASE,
)


def log_path() -> Path:
    return Path("~/.ccdeck/ccdeck.log").expanduser()


def redact(text: str) -> str:
    """Hide API keys and similar values before they reach the log."""
    return SECRET_RE.sub(lambda m: (m.group(1) + "***") if m.group(1) else "sk-ant-***", text)


class _Redacting(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup() -> None:
    """(Re)attach the file handler for the current HOME. Safe to call more than once."""
    for h in list(log.handlers):
        log.removeHandler(h)
        h.close()
    debug = os.environ.get("CCDECK_DEBUG", "") not in ("", "0")
    log.setLevel(logging.DEBUG if debug else logging.INFO)
    log.propagate = False
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(_Redacting(
        "%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
    log.addHandler(handler)


def tail(n: int = 60) -> str:
    try:
        lines = log_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])
