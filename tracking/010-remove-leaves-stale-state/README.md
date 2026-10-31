# Removing a session leaves its state file; re-adding the name shows old data

| Field | Value |
|---|---|
| Status | done |
| Type | ux |
| Priority | P3 |
| Size | S |
| Verified | reviewer read |
| Source | ccdeck review, 2026-10-29 |

## Problem

`d` removes the session from config but not `~/.ccdeck/state/<name>.json` on the host, so a new session with the same name shows the old prompt/message.

## Where

- `ccdeck/tui.py:469` `action_remove_session()`

## Proposed fix

After a successful save, delete the state file on that host in a worker (`rm -f`). Ignore failures (host offline) but log them.

## Done when

- [x] Test: add → run → stop → remove → add same name → no old prompt.

## Notes

_Add findings, decisions and links to commits here._

## Review (2026-10-31)

**Verdict:** confirmed. **Priority:** P2 → P3.

- `action_remove_session()` only saves the config. However, `start_script()` already runs `rm -f ~/.ccdeck/state/<name>.json` before every start, so the old data only shows until the re-added session is first started: the last message, the age and, now, the old **conversation** in the auto preview (stopped sessions show the transcript). It is cosmetic and goes away on start, hence P3.
- **Fix:** sound. Delete the state file on the *old* host, which matters if the re-added session uses a different host. Do the same when a session is renamed or moved to another host in `e`.
- **Missing, related:** `~/.ccdeck/env/<name>.sh` is never removed either, by remove or anywhere else. It holds the account's env, including `ANTHROPIC_API_KEY` (mode 0600), and it stays on every host the session ever ran on, even after the key is taken out of the config. Delete it in the same command: `rm -f state/<name>.json env/<name>.sh`.

## Fix (2026-10-31)

Removing a session deletes its state and env files on its host (`sessions.forget`, run in a worker). Test: `test_forms.py::test_add_edit_remove_session_from_ui`.
