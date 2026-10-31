# A failed start left the account's env file (API key) on the host

| Field | Value |
|---|---|
| Status | done |
| Type | bug/security |
| Priority | P2 |
| Size | S |
| Verified | confirmed (test) |
| Source | bug hunt after 045, 2026-10-31 |

## Problem

Since 042, only the pane deletes `~/.derot/env/<name>.sh`. If writing the run file or `tmux new-session` failed after the env file was written, no pane ever ran. The secrets then stayed on disk until the next successful start or a remove.

## Where

`derot/sessions.py` `start_script()` (line 374)

## Fix

If any step after the env file is written fails, the env file is deleted before exiting with the same code.

## Done when

- [x] Covered by a test.

## Notes

Test: `test_bughunt_new.py::test_049_failed_start_removes_the_env_file`. Still open, suspected: `login()` writes `_login.sh` in a separate call before `ssh -t`. If that interactive step never runs the pane (connection drop), the file stays until the next login.
