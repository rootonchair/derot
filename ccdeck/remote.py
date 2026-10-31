"""Run commands on a host: a local subprocess, or the same command wrapped in ssh."""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

from .config import Host
from .log import log

DEFAULT_TIMEOUT = 20


def ssh_opts(batch: bool = True) -> List[str]:
    ssh_dir = Path("~/.ccdeck/ssh").expanduser()
    ssh_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(ssh_dir, 0o700)
    except OSError:
        pass
    opts = [
        "-o", "ControlMaster=auto",
        "-o", f"ControlPath={ssh_dir}/%C",
        "-o", "ControlPersist=10m",
        "-o", "ConnectTimeout=8",
    ]
    if batch:
        opts += ["-o", "BatchMode=yes"]
    return opts


def local_env() -> dict:
    """Environment for local tmux calls: without TMUX so it works inside the user's tmux."""
    env = dict(os.environ)
    env.pop("TMUX", None)
    env.pop("TMUX_PANE", None)
    return env


def wrap(host: Host, argv: Sequence[str], tty: bool = False) -> List[str]:
    """The argv to execute locally to run `argv` on `host`."""
    if host.is_local:
        return list(argv)
    opts = ssh_opts(batch=not tty)
    return ["ssh", *(["-t"] if tty else []), *opts, str(host.ssh), shlex.join(list(argv))]


def run(
    host: Host,
    argv: Sequence[str],
    input: Optional[str] = None,
    timeout: Optional[float] = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess:
    """Run argv on host and capture output. Never raises for process failures."""
    cmd = wrap(host, argv)
    try:
        child = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=local_env(),
            # no controlling terminal: an interactive login shell (`$SHELL -lic`, used to
            # find claude) run from a worker must never grab, or be stopped by, the
            # terminal the console draws on
            start_new_session=True,
        )
    except OSError as e:
        log.error("on %s: couldn't run %s: %s", host.name, describe(argv), e)
        return subprocess.CompletedProcess(cmd, 127, "", str(e))
    try:
        out, err = child.communicate(input, timeout=timeout)
    except subprocess.TimeoutExpired:
        # the whole process group, not just `sh`/`ssh`: a login shell or python3 it
        # started would otherwise keep running (stuck) after the timeout
        _kill_group(child)
        log.warning("on %s: timed out after %ss: %s", host.name, timeout, describe(argv))
        return subprocess.CompletedProcess(cmd, 255, "", f"timed out after {timeout}s")
    except BaseException:
        _kill_group(child)
        raise
    proc = subprocess.CompletedProcess(cmd, child.returncode, out, err)
    if log.isEnabledFor(10):
        log.debug("on %s: rc=%s %s%s", host.name, proc.returncode, describe(argv),
                  f"\n  stderr: {proc.stderr.strip()[-2000:]}" if proc.stderr.strip() else "")
    return proc


def _kill_group(child: subprocess.Popen) -> None:
    try:
        os.killpg(child.pid, signal.SIGKILL)  # its own group (start_new_session)
    except OSError:
        pass
    try:
        child.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    for f in (child.stdin, child.stdout, child.stderr):
        try:
            if f:
                f.close()
        except OSError:
            pass


def sh(
    host: Host,
    script: str,
    *args: str,
    input: Optional[str] = None,
    timeout: Optional[float] = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess:
    """Run a POSIX sh script on host. Extra args become $1, $2, ..."""
    return run(host, ["sh", "-c", script, "sh", *args], input=input, timeout=timeout)


def python(
    host: Host,
    code: str,
    *args: str,
    timeout: Optional[float] = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess:
    """Run a python3 snippet on host. Extra args land in sys.argv[1:]."""
    return run(host, ["python3", "-c", code, *args], timeout=timeout)


def interactive(host: Host, argv: Sequence[str]) -> int:
    """Run argv on host attached to the current terminal (ssh -t for remote)."""
    log.debug("on %s: interactive %s", host.name, describe(argv))
    try:
        code = subprocess.call(wrap(host, argv, tty=True), env=local_env())
    except OSError as e:
        log.error("on %s: couldn't run %s: %s", host.name, describe(argv), e)
        print(f"[ccdeck] {e}")
        return 127
    if code not in (0, 130):
        log.warning("on %s: %s exited with %s", host.name, describe(argv), code)
    return code


def describe(argv: Sequence[str], limit: int = 400) -> str:
    """A short, readable form of a command for the log."""
    text = shlex.join(list(argv))
    return text if len(text) <= limit else text[: limit - 1] + "…"


def qpath(path: str) -> str:
    """Shell-quote a path but keep a leading ~ expandable: ~/x -> "$HOME"/'x'."""
    if path == "~":
        return '"$HOME"'
    if path.startswith("~/"):
        rest = path[2:]
        return '"$HOME"/' + shlex.quote(rest) if rest else '"$HOME"/'
    return shlex.quote(path)


def last_line(text: str) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return lines[-1] if lines else ""


def full_error(proc: subprocess.CompletedProcess) -> str:
    """All of stderr (or stdout) for the log, not just the last line."""
    text = (proc.stderr or "").strip() or (proc.stdout or "").strip()
    return text[-4000:] or f"exit code {proc.returncode}"


def error_text(proc: subprocess.CompletedProcess) -> str:
    return last_line(proc.stderr) or last_line(proc.stdout) or f"exit code {proc.returncode}"
