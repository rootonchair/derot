import json
import os
import subprocess
import sys
from pathlib import Path

from ccdeck import hook

HOOK = Path(hook.__file__)


def run_hook(env_home, event, payload, session="s1"):
    env = dict(os.environ, HOME=str(env_home))
    if session:
        env["CCDECK_SESSION"] = session
    else:
        env.pop("CCDECK_SESSION", None)
    p = subprocess.run([sys.executable, str(HOOK), event], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    return p


def state(home, session="s1"):
    return json.loads((home / ".ccdeck" / "state" / f"{session}.json").read_text())


def test_event_sequence(tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        json.dumps({"type": "assistant", "message": {"content": "older"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {
            "content": [{"type": "tool_use"}, {"type": "text", "text": "Final\nanswer"}]}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use"}]}}) + "\n"
        + "not json\n"
    )
    steps = [
        ("SessionStart", {}, "idle", ""),
        ("UserPromptSubmit", {"prompt": "fix\nthe bug " + "x" * 300}, "busy", ""),
        ("PreToolUse", {"tool_name": "Bash"}, "busy", "using Bash"),
        ("Notification", {"message": "Claude needs your permission to use Bash"}, "waiting",
         "Claude needs your permission to use Bash"),
        ("PostToolUse", {"tool_name": "Bash"}, "busy", "using Bash"),
        ("Stop", {"transcript_path": str(transcript)}, "done", "Final answer"),
        ("Notification", {"message": "Claude is waiting for your input"}, "done", "Final answer"),
        ("SessionEnd", {}, "stopped", "Final answer"),
    ]
    for event, payload, want_state, want_msg in steps:
        p = run_hook(tmp_path, event, dict(payload, cwd="/w"))
        assert p.returncode == 0 and p.stdout == ""
        s = state(tmp_path)
        assert (s["state"], s["message"]) == (want_state, want_msg), event
        assert s["event"] == event and s["session"] == "s1" and s["cwd"] == "/w"
    s = state(tmp_path)
    assert s["prompt"].startswith("fix the bug x") and len(s["prompt"]) <= 160
    assert set(s) >= {"session", "state", "event", "ts", "cwd", "prompt", "message"}


def test_idle_nudge_sets_idle_when_not_done(tmp_path):
    run_hook(tmp_path, "UserPromptSubmit", {"prompt": "hi"})
    run_hook(tmp_path, "Notification", {"message": "x", "notification_type": "idle_prompt"})
    assert state(tmp_path)["state"] == "idle"


def test_stop_without_transcript_says_finished(tmp_path):
    run_hook(tmp_path, "Stop", {"transcript_path": str(tmp_path / "missing.jsonl")})
    assert state(tmp_path)["message"] == "finished"


def test_noop_without_session_and_survives_garbage(tmp_path):
    p = run_hook(tmp_path, "Stop", {}, session=None)
    assert p.returncode == 0 and not (tmp_path / ".ccdeck").exists()
    env = dict(os.environ, HOME=str(tmp_path), CCDECK_SESSION="s1")
    p = subprocess.run([sys.executable, str(HOOK), "Stop"], input="{{{", capture_output=True,
                       text=True, env=env)
    assert p.returncode == 0 and p.stdout == ""
    (tmp_path / ".ccdeck" / "state" / "s1.json").write_text("garbage")
    assert run_hook(tmp_path, "SessionStart", {}).returncode == 0
    assert state(tmp_path)["state"] == "idle"
