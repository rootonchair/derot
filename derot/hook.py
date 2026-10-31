#!/usr/bin/env python3
"""derot status hook for Claude Code.

Installed to ~/.derot/hook.py and called as `python3 ~/.derot/hook.py <EventName>` with
the hook JSON payload on stdin. Writes ~/.derot/state/<DEROT_SESSION>.json.

Rules: stdlib only, never write to stdout, always exit 0.
`hook.py --dump` is used by the poller instead: it prints every state file to stdout.
"""

import json
import os
import sys
import tempfile
import time

STATE_DIR = os.path.join(os.path.expanduser("~"), ".derot", "state")
ERROR_LOG = os.path.join(os.path.expanduser("~"), ".derot", "hook-errors.log")
ERROR_LOG_MAX = 256 * 1024
TAIL_BYTES = 200 * 1024
FIELDS = ("session", "state", "event", "ts", "cwd", "prompt", "message", "session_id",
          "transcript_path")


def one_line(text, limit=None):
    text = " ".join(str(text or "").split())
    if limit and len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def text_of(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "\n".join(p for p in parts if p).strip()
    return ""


def last_assistant_text(path):
    if not path:
        return ""
    try:
        path = os.path.expanduser(path)
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - TAIL_BYTES))
            data = f.read()
    except Exception:
        return ""
    for raw in reversed(data.splitlines()):
        try:
            entry = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            continue
        try:
            if not isinstance(entry, dict) or entry.get("type") != "assistant":
                continue
            msg = entry.get("message")
            if not isinstance(msg, dict):
                continue
            text = text_of(msg.get("content"))
            if text:
                return text
        except Exception:
            continue
    return ""


def read_state(path):
    try:
        with open(path) as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def write_state(path, data):
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def is_idle_nudge(payload):
    if payload.get("notification_type") == "idle_prompt":
        return True
    return "waiting for your input" in str(payload.get("message") or "").lower()


def tool_summary(payload):
    """`Bash: npm test` / `Edit: src/app.py` / `WebFetch` for a permission request."""
    tool = str(payload.get("tool_name") or "a tool")
    inp = payload.get("tool_input")
    if isinstance(inp, dict):
        detail = inp.get("command") or inp.get("file_path") or inp.get("url") or inp.get("pattern")
        if isinstance(detail, list):  # Codex can pass argv
            detail = " ".join(str(a) for a in detail)
        if detail:
            return one_line("%s: %s" % (tool, detail), 160)
    return tool


def owns(state, event, payload):
    """False for events from a different Claude process that inherited DEROT_SESSION.

    The first SessionStart in a fresh state file claims the session. Later, only the same
    session_id may update it, except /clear, /resume and compaction, which switch the id.
    A child `claude` started from inside the session reports source "startup" and is ignored.
    """
    sid, mine = payload.get("session_id"), state.get("session_id")
    if not mine:
        # a fresh state file (start deletes it): a session that was just stopped can still
        # be ending - its late SessionEnd must not claim the file before the new one starts
        return event != "SessionEnd" or not sid
    if not sid or sid == mine:
        return True
    return event == "SessionStart" and payload.get("source") in ("clear", "resume", "compact")


# Notification types that mean Claude is blocked on you; others are informational.
# No type at all (older Claude Code) still counts as needs-you.
NEEDS_YOU = ("permission_prompt", "elicitation_dialog", "elicitation_url_dialog",
             "agent_needs_input")
STATES_KEPT_ON_COMPACT = ("busy", "waiting", "done", "idle")


def apply(state, event, payload):
    """Return the new state dict for this event (pure; easy to test)."""
    current = state.get("state")
    alert = False  # entering a state worth an alert; counted so a repeat isn't missed
    if event == "SessionStart":
        # compaction (auto, when the context fills) can happen mid-turn: keep the state
        if payload.get("source") != "compact" or current not in STATES_KEPT_ON_COMPACT:
            state["state"] = "idle"
            state["message"] = ""
    elif event == "UserPromptSubmit":
        state["state"] = "busy"
        state["prompt"] = one_line(payload.get("prompt"), 160)
        state["message"] = ""
    elif event in ("PreToolUse", "PostToolUse"):
        state["state"] = "busy"
        state["message"] = one_line("using " + str(payload.get("tool_name") or "a tool"))
    elif event == "PermissionRequest":
        state["state"] = "waiting"
        state["message"] = "wants to use " + tool_summary(payload)
        alert = True
    elif event == "PostToolUseFailure":
        if payload.get("is_interrupt"):
            state["state"] = "idle"
            state["message"] = "interrupted"
        else:
            state["state"] = "busy"
            tool = payload.get("tool_name") or "a tool"
            state["message"] = one_line("using %s (it failed)" % tool)
    elif event == "Notification":
        message = one_line(payload.get("message"))
        kind = payload.get("notification_type")
        if kind and kind not in NEEDS_YOU and kind != "idle_prompt":
            pass  # informational (auth_success, agent_completed, ...): nothing to do
        elif is_idle_nudge(payload):
            if current not in ("done", "waiting"):  # keep a result / a pending prompt
                state["state"] = "idle"
                state["message"] = message
        elif current == "waiting" and str(state.get("message", "")).startswith("wants to use "):
            pass  # keep the more specific PermissionRequest text
        else:
            state["state"] = "waiting"
            state["message"] = message
            alert = True
    elif event == "Stop":
        state["state"] = "done"
        alert = True
        text = payload.get("last_assistant_message") or last_assistant_text(
            payload.get("transcript_path"))
        state["message"] = one_line(text) or "finished"
    elif event == "StopFailure":
        state["state"] = "done"
        alert = True
        state["message"] = one_line("stopped with an error: %s" % (
            payload.get("error_details") or payload.get("error") or "unknown"), 300)
    elif event == "Interrupt":  # Codex: you interrupted the turn (Esc)
        state["state"] = "idle"
        state["message"] = "interrupted"
    elif event == "SessionEnd":
        state["state"] = "stopped"
    else:
        return None
    if alert:
        state["alerts"] = int(state.get("alerts") or 0) + 1
    state["event"] = event
    return state


INTERRUPTED = "[Request interrupted by user"
DECLINED = "doesn't want to proceed with this tool use"


def last_entry(path):
    """The last user/assistant transcript entry, or None."""
    try:
        with open(os.path.expanduser(path), "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 64 * 1024))
            data = f.read()
    except Exception:
        return None
    for raw in reversed(data.splitlines()):
        try:
            entry = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            continue
        if isinstance(entry, dict) and entry.get("type") in ("user", "assistant"):
            return entry
    return None


def reconcile(state):
    """Fix states that no hook clears: Esc-interrupts and declined permissions.

    If the transcript changed after the last hook event and now ends with an interrupt
    marker (or, while waiting, a declined tool result), Claude is idle, not busy/waiting.
    """
    if state.get("state") not in ("waiting", "busy"):
        return state
    path = state.get("transcript_path")
    try:
        if not path or os.path.getmtime(os.path.expanduser(path)) <= float(state.get("ts") or 0):
            return state
    except Exception:
        return state
    entry = last_entry(path)
    if not entry or entry.get("type") != "user":
        return state
    content = (entry.get("message") or {}).get("content")
    blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
    for b in blocks:
        if not isinstance(b, dict):
            continue
        text = b.get("text") if b.get("type") == "text" else b.get("content")
        text = text if isinstance(text, str) else json.dumps(text)
        if INTERRUPTED in (text or ""):
            state["state"], state["message"] = "idle", "interrupted"
        elif state.get("state") in ("waiting", "busy") and b.get("type") == "tool_result" \
                and b.get("is_error") and DECLINED in (text or ""):
            state["state"], state["message"] = "idle", "you declined the request"
    return state


def dump():
    """Print every state file as one JSON line (for the poller), after reconcile()."""
    try:
        names = sorted(os.listdir(STATE_DIR))
    except Exception:
        return
    for name in names:
        if not name.endswith(".json") or name.startswith("."):
            continue
        state = read_state(os.path.join(STATE_DIR, name))
        if not state:
            continue
        try:
            state = reconcile(state)
        except Exception:
            pass
        sys.stdout.write(json.dumps(state) + "\n")


def main():
    if sys.argv[1:2] == ["--dump"]:
        dump()
        return
    session = os.environ.get("DEROT_SESSION")
    if not session or "/" in session or session.startswith("."):
        return
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}
    event = event or str(payload.get("hook_event_name") or "")

    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, session + ".json")
    state = read_state(path)
    if not owns(state, event, payload):
        return
    new = apply(state, event, payload)
    if new is None:
        return
    new["session"] = session
    new["ts"] = time.time()
    for key in ("cwd", "session_id", "transcript_path"):
        if payload.get(key):
            new[key] = payload.get(key)
    for key in FIELDS:
        new.setdefault(key, "")
    write_state(path, new)


def log_error():
    """Append the current traceback to ~/.derot/hook-errors.log (never stdout)."""
    try:
        import traceback
        if os.path.exists(ERROR_LOG) and os.path.getsize(ERROR_LOG) > ERROR_LOG_MAX:
            os.replace(ERROR_LOG, ERROR_LOG + ".1")
        with open(ERROR_LOG, "a") as f:
            f.write("%s session=%s event=%s\n%s\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), os.environ.get("DEROT_SESSION"),
                sys.argv[1:], traceback.format_exc()))
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        log_error()
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(0)
