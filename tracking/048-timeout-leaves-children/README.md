# A timed-out command left its children running

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | confirmed (test) |
| Source | bug hunt after 045, 2026-10-31 |

## Problem

`subprocess.run(timeout=…)` kills only the direct child (`sh` or `ssh`). Whatever it had started kept running after the timeout: an interactive login shell (`$SHELL -lic env` in the setup check) stuck in a slow rc file, or a python3 snippet.

## Where

`ccdeck/remote.py` `run()` (line 52), `_kill_group()` (line 94)

## Fix

`run()` uses Popen plus communicate. On a timeout, or any exception, it kills the child's whole process group, which exists because of `start_new_session=True`.

## Done when

- [x] Covered by a test.

## Notes

Test: `test_bughunt_new.py::test_048_timeout_kills_the_whole_command`. On remote hosts, killing ssh doesn't necessarily stop the remote command, because there is no pty and so no SIGHUP. Not handled.
