#!/usr/bin/env python3
"""Fake Claude Code for tests: runs settings.json hooks like the real thing.

At the permission prompt: Enter approves, `n` declines (like real Claude Code: a rejected
tool_result in the transcript, no PostToolUse/Stop), `esc` interrupts (interrupt marker,
PostToolUseFailure with is_interrupt). Supports the newer events "PermissionRequest",
"PostToolUseFailure" and "StopFailure" (the installer greps for these names).
"""

import json
import os
import subprocess
import sys
import time

import glob
import re

cdir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
cdir = os.path.expanduser(cdir)
# the real layout: <config dir>/projects/<cwd, non-alphanumerics as ->/<session id>.jsonl
project = os.path.join(cdir, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.getcwd()))
session_id = f"fake-{os.getpid()}"
argv = sys.argv[1:]
if "--resume" in argv:
    session_id = argv[argv.index("--resume") + 1]
elif "--continue" in argv:
    previous = sorted(glob.glob(os.path.join(project, "*.jsonl")), key=os.path.getmtime)
    if previous:
        session_id = os.path.basename(previous[-1])[:-len(".jsonl")]
transcript = os.path.join(project, f"{session_id}.jsonl")


def settings():
    try:
        with open(os.path.join(cdir, "settings.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def fire(event, **extra):
    payload = {
        "session_id": session_id,
        "hook_event_name": event,
        "cwd": os.getcwd(),
        "transcript_path": transcript,
        **extra,
    }
    for group in (settings().get("hooks") or {}).get(event, []):
        matcher = group.get("matcher")
        tool = extra.get("tool_name")
        if matcher and tool and matcher not in ("*", "") and matcher != tool:
            continue
        for h in group.get("hooks", []):
            if h.get("type") != "command":
                continue
            res = subprocess.run(["sh", "-c", h["command"]], input=json.dumps(payload),
                                 capture_output=True, text=True, timeout=h.get("timeout", 60))
            if res.stdout:
                print(f"[fake-claude] hook stdout: {res.stdout!r}")
            if res.returncode != 0:
                print(f"[fake-claude] hook failed ({res.returncode}): {res.stderr.strip()}")


def log_entry(entry):
    os.makedirs(project, exist_ok=True)  # like Claude: created with the first message
    with open(transcript, "a") as f:
        f.write(json.dumps(dict(entry, sessionId=session_id)) + "\n")


def main():
    args = sys.argv[1:]
    print(f"[fake-claude] account={cdir} args={' '.join(args)} cwd={os.getcwd()}", flush=True)
    with open(os.path.join(cdir, "fake-claude-runs.log"), "a") as f:
        f.write(json.dumps({"args": args, "cwd": os.getcwd(),
                            "session": os.environ.get("DEROT_SESSION"),
                            "config_dir_env": os.environ.get("CLAUDE_CONFIG_DIR"),
                            "test_var": os.environ.get("DEROT_TEST_VAR")}) + "\n")
    resumed = "--continue" in args or "--resume" in args
    fire("SessionStart", source="resume" if resumed else "startup")
    while True:
        print("> ", end="", flush=True)
        line = sys.stdin.readline()
        if not line or line.strip() == "/exit":
            fire("SessionEnd", reason="exit")
            return
        prompt = line.strip()
        if not prompt:
            continue
        fire("UserPromptSubmit", prompt=prompt)
        tool = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        log_entry({"type": "user", "message": {"content": prompt}})
        log_entry({"type": "ai-title", "aiTitle": f"About {prompt}"})
        log_entry({"type": "last-prompt", "lastPrompt": prompt})
        log_entry({"type": "assistant", "message": {"content": [{"type": "tool_use"}]}})
        fire("PreToolUse", **tool)
        fire("PermissionRequest", **tool)
        time.sleep(0.3)
        fire("Notification", message="Claude needs your permission to use Bash",
             notification_type="permission_prompt")
        print("[fake-claude] allow Bash? (Enter / n / esc)", flush=True)
        answer = sys.stdin.readline().strip()
        time.sleep(0.05)
        if answer == "n":
            log_entry({"type": "user", "message": {"content": [{
                "type": "tool_result", "is_error": True, "tool_use_id": "t1",
                "content": "The user doesn't want to proceed with this tool use. "
                           "The tool use was rejected."}]}})
            continue
        if answer == "esc":
            fire("PostToolUseFailure", error="interrupted", is_interrupt=True, **tool)
            log_entry({"type": "user", "message": {"content": [{
                "type": "text", "text": "[Request interrupted by user for tool use]"}]}})
            continue
        fire("PostToolUse", **tool)
        reply = f"All done with: {prompt}"
        log_entry({"type": "assistant", "message": {"content": [{"type": "text", "text": reply}]}})
        print(reply, flush=True)
        fire("Stop", last_assistant_message=reply)


if __name__ == "__main__":
    main()
