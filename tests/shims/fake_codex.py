#!/usr/bin/env python3
"""Fake Codex CLI for tests: runs hooks.json hooks like the real thing (0.164).

Events and payloads follow developers.openai.com/codex/hooks. Transcripts go where Codex
keeps them: <CODEX_HOME>/sessions/YYYY/MM/DD/rollout-<time>-<id>.jsonl, starting with a
session_meta line, titles in <CODEX_HOME>/session_index.jsonl.

  codex [flags]               new session
  codex resume [flags] ID     resume that session
  codex resume [flags] --last resume the newest session in this folder
  codex login                 pretend to log in

At the approval prompt: Enter approves, `n` declines, `esc` interrupts (Interrupt event).
FAKE_CODEX_UNTRUSTED=1 skips every hook, like hooks nobody approved in /hooks yet.
"""

import glob
import json
import os
import subprocess
import sys
import time
import uuid

home = os.path.expanduser(os.environ.get("CODEX_HOME") or "~/.codex")
args = sys.argv[1:]


def newest_here():
    best = None
    for path in glob.glob(os.path.join(home, "sessions", "*", "*", "*", "rollout-*.jsonl")):
        try:
            with open(path) as f:
                meta = json.loads(f.readline())["payload"]
        except Exception:
            continue
        if meta.get("cwd") == os.getcwd() and (best is None
                                               or os.path.getmtime(path) > best[0]):
            best = (os.path.getmtime(path), path, meta["id"])
    return best


resumed = bool(args) and args[0] == "resume"
session_id, transcript = None, None
if resumed:
    rest = [a for a in args[1:] if not a.startswith("-")]
    if "--last" in args:
        found = newest_here()
        if found:
            _, transcript, session_id = found
    elif rest:
        session_id = rest[-1]
        hits = glob.glob(os.path.join(home, "sessions", "*", "*", "*",
                                      f"rollout-*-{session_id}.jsonl"))
        transcript = hits[0] if hits else None
if not session_id:
    session_id = str(uuid.uuid4())
if not transcript:
    day = time.strftime("%Y/%m/%d")
    transcript = os.path.join(home, "sessions", day,
                              f"rollout-{time.strftime('%Y-%m-%dT%H-%M-%S')}-{session_id}.jsonl")


def hooks():
    if os.environ.get("FAKE_CODEX_UNTRUSTED") == "1":
        return {}
    try:
        with open(os.path.join(home, "hooks.json")) as f:
            return json.load(f).get("hooks") or {}
    except Exception:
        return {}


def fire(event, **extra):
    payload = {"session_id": session_id, "transcript_path": transcript, "cwd": os.getcwd(),
               "hook_event_name": event, "model": "fake-codex", **extra}
    for group in hooks().get(event, []):
        matcher, tool = group.get("matcher"), extra.get("tool_name")
        if matcher and tool and matcher not in ("*", "") and matcher != tool:
            continue
        for h in group.get("hooks", []):
            if h.get("type") == "command":
                subprocess.run(["sh", "-c", h["command"]], input=json.dumps(payload),
                               capture_output=True, text=True, timeout=h.get("timeout", 600))


def record(kind, payload):
    os.makedirs(os.path.dirname(transcript), exist_ok=True)
    fresh = not os.path.exists(transcript)
    with open(transcript, "a") as f:
        if fresh:
            f.write(json.dumps({"type": "session_meta", "payload": {
                "id": session_id, "cwd": os.getcwd(), "cli_version": "0.164.0"}}) + "\n")
        f.write(json.dumps({"type": kind, "payload": payload}) + "\n")


def message(role, text):
    block = "output_text" if role == "assistant" else "input_text"
    record("response_item", {"type": "message", "role": role,
                             "content": [{"type": block, "text": text}]})


def main():
    if args[:1] == ["login"]:
        print("[fake-codex] logged in", flush=True)
        return
    with open(os.path.join(home, "fake-codex-runs.log"), "a") as f:
        f.write(json.dumps({"args": args, "cwd": os.getcwd(),
                            "session": os.environ.get("DEROT_SESSION"),
                            "codex_home_env": os.environ.get("CODEX_HOME")}) + "\n")
    print(f"[fake-codex] home={home} args={' '.join(args)}", flush=True)
    turn = 0  # like real Codex 0.164: SessionStart (fresh sessions only) comes with turn 1
    while True:
        print("› ", end="", flush=True)
        line = sys.stdin.readline()
        if not line or line.strip() == "/exit":
            fire("SessionEnd", reason="other")
            return
        prompt = line.strip()
        if not prompt:
            continue
        turn += 1
        turn_id = f"t{turn}"
        if turn == 1 and not resumed:
            fire("SessionStart", source="startup")
        message("user", "<environment_context>cwd</environment_context>")  # injected
        message("user", prompt)
        with open(os.path.join(home, "session_index.jsonl"), "a") as f:
            f.write(json.dumps({"id": session_id, "thread_name": f"Codex: {prompt}",
                                "updated_at": time.time()}) + "\n")
        fire("UserPromptSubmit", turn_id=turn_id, prompt=prompt)
        tool = {"tool_name": "shell", "tool_input": {"command": ["bash", "-lc", "ls"]}}
        fire("PreToolUse", turn_id=turn_id, tool_use_id="c1", **tool)
        fire("PermissionRequest", turn_id=turn_id, **tool)
        print("[fake-codex] allow shell? (Enter / n / esc)", flush=True)
        answer = sys.stdin.readline().strip()
        if answer == "esc":
            fire("Interrupt", turn_id=turn_id)
            record("event_msg", {"type": "turn_aborted", "turn_id": turn_id})
            continue
        if answer == "n":
            reply = "OK, I won't run it."
        else:
            fire("PostToolUse", turn_id=turn_id, tool_use_id="c1", tool_response="ok", **tool)
            reply = f"Codex did: {prompt}"
        message("assistant", reply)
        print(reply, flush=True)
        fire("Stop", turn_id=turn_id, stop_hook_active=False, last_assistant_message=reply)


if __name__ == "__main__":
    main()
