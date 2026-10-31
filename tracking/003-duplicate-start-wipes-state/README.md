# Starting an already-running session wipes its status

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P0 |
| Size | S |
| Verified | confirmed (reviewer read; easy to reproduce) |
| Source | ccdeck review, 2026-10-29 |

## Problem

`start_script` runs `rm -f state/<name>.json` before `new-session`. If the session is already running, `new-session` fails with "duplicate session" but the state file is already gone, so the row drops to plain `idle` and loses its prompt/message.

## Where

- `ccdeck/sessions.py:263` `start_script()`

## Proposed fix

Guard the whole script: `tmux -L ccdeck has-session -t '=cc-<name>' 2>/dev/null && { echo 'duplicate session: cc-<name>' >&2; exit 1; }` before the `rm`.

## Done when

- [x] Test: start → drive to `done` → start again → error "already running" **and** status is still `done` with the same message.

## Notes

**2026-10-29:** `start_script()` now runs `has-session -t =cc-<name>:` first and exits with "duplicate session" before touching the state file. Test: `test_003_starting_a_running_session_keeps_its_status` (fails on the old code).
