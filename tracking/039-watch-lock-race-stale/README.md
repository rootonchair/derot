# `watch` lock isn't atomic and survives SIGTERM

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | suspected (code reading) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

`acquire_watch_lock()` checks the pid file, then writes it: two `ccdeck watch` processes started together (login items, a launchd restart overlapping) can both take the lock and send every alert twice. The file is removed only by `atexit`, which doesn't run on SIGTERM (how launchd stops a job, see 016); the stale pid can later match an unrelated process, and the console then leaves desktop alerts to a `watch` that isn't running.

## Where

- `ccdeck/notify.py:79` `acquire_watch_lock()`
- `ccdeck/notify.py:62` `watch_running()`
- `ccdeck/cli.py:121` `cmd_watch()`

## Proposed fix

Hold an `fcntl.flock(LOCK_EX | LOCK_NB)` on an open lock file for the life of the process (released on any exit, so no stale state); `watch_running()` tests the lock the same way.

## Done when

- [x] Two concurrent `watch` starts: exactly one runs. After `kill -TERM`, the console sends desktop alerts again.

## Notes

_Add findings, decisions and links to commits here._

## Review (2026-10-31)

**Verdict:** confirmed by reading the code. **Priority:** P3 (unchanged; raise it to P2 when 016's launchd service lands).

- The check-then-write race is real, but both processes would have to start within milliseconds of each other. The SIGTERM case is more likely: Python's default SIGTERM handling skips `atexit`, so `watch.pid` stays behind. If the pid is later reused, `watch_running()` returns True and the console silently stops sending desktop alerts. That is a missed alert and gives no sign.
- **Fix:** sound. `flock(LOCK_EX|LOCK_NB)` on a file held open for the life of the process; `watch_running()` tries the same lock non-blocking and releases it at once. The pid file can stay for information only. A SIGTERM handler that raises `SystemExit` would be a smaller partial fix, but it doesn't fix the race.

## Fix (2026-10-31)

The lock is an `flock` held for the life of `watch` (atomic; released by the kernel on any exit). Test: `test_bugfixes.py::test_007_console_leaves_desktop_alerts_to_watch`.
