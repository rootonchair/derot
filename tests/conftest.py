import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from derot import sessions

SHIMS = Path(__file__).parent / "shims"


def wait_for(fn, timeout=15.0, interval=0.2, what="condition"):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {what} (last: {last!r})")


class Env:
    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.vms = root / "vms"
        self.bin = root / "bin"
        self.claude = self.bin / "claude"
        self.config = self.home / ".config" / "derot" / "config.yaml"

    def vm_home(self, host="vm") -> Path:
        return self.vms / host / "home"

    def host_env(self, host="local") -> dict:
        env = dict(os.environ)
        env.pop("TMUX", None)
        if host != "local":
            env["HOME"] = str(self.vm_home(host))
            env["TMUX_TMPDIR"] = str(self.vms / host / "tmux")
        return env

    def tmux(self, *args, host="local"):
        return subprocess.run(["tmux", "-L", "derot", *args], capture_output=True, text=True,
                              env=self.host_env(host))

    def send(self, name, text, host="local"):
        args = ["send-keys", "-t", sessions.tmux_name(name)]
        if text:
            args.append(text)
        self.tmux(*args, "Enter", host=host)

    def pane(self, name, host="local") -> str:
        return self.tmux("capture-pane", "-p", "-t", sessions.tmux_name(name),
                         host=host).stdout

    def write_config(self, text: str):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(text.replace("@CLAUDE@", str(self.claude)))

    def write_json(self, path: Path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))


@pytest.fixture
def env(monkeypatch):
    # tmux sockets need a short path, so this lives directly under /tmp
    root = Path(tempfile.mkdtemp(prefix="ccd", dir="/tmp")).resolve()
    e = Env(root)
    for d in (e.home, e.vms, e.bin, root / "tmux"):
        d.mkdir(parents=True)
    shutil.copy(SHIMS / "ssh", e.bin / "ssh")
    src = (SHIMS / "fake_claude.py").read_text().splitlines()
    src[0] = f"#!{sys.executable}"
    e.claude.write_text("\n".join(src) + "\n")
    for f in (e.bin / "ssh", e.claude):
        f.chmod(0o755)

    monkeypatch.setenv("HOME", str(e.home))
    monkeypatch.setenv("TMUX_TMPDIR", str(root / "tmux"))
    monkeypatch.setenv("FAKE_SSH_ROOT", str(e.vms))
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.setenv("DEROT_CONFIG", str(e.config))
    monkeypatch.setenv("PATH", f"{e.bin}:{os.environ['PATH']}")
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    yield e
    for host in ["local", *[p.name for p in e.vms.iterdir()]]:
        e.tmux("kill-server", host=host)
    shutil.rmtree(root, ignore_errors=True)


needs_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")
