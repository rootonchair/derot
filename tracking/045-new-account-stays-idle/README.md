# A new account's session stayed "idle" forever (hook setup interrupted)

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P1 |
| Size | S |
| Verified | confirmed (user report + test) |
| Source | user report, 2026-10-31 |

## Problem

After saving a session with a new account (`work`), the background hook setup logged "setup on local" and never finished (no result, no error). `~/.claude-work` was never created, so the session had no hooks and could only show "idle". Likely causes: the console was restarted mid-setup, or the interactive login shell (`$SHELL -lic`) run from the worker was stopped by the terminal. Nothing retried.

## Where

- `ccdeck/tui.py` `install_hooks_worker` (fire-and-forget)
- `ccdeck/remote.py` `run()`

## Fix

- `installer.ensure_hooks()` before every start (`start_worker`, `ccdeck start`): one quick check of the account folder's settings (and, since 046/047, the hook file's hash); runs setup if anything is missing, warns if that fails.
- `remote.run()` uses `start_new_session=True`: worker commands have no controlling terminal.

## Done when

- [x] Covered by a test.

## Notes

Tests: `test_045_*` in `tests/test_bughunt_new.py`; `test_sessions.py::test_idle_without_hooks` now creates the session without `ccdeck start`.
