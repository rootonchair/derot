# Child `claude` processes overwrite the parent session's status

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P1 |
| Size | S |
| Verified | likely |
| Source | derot review, 2026-10-29 |

## Problem

`DEROT_SESSION` is exported in the pane, so any `claude` that the session itself spawns (sub-runs, scripts, `claude -p` in Bash) inherits it and its hooks write into the parent's state file.

## Where

- `derot/sessions.py:224` `inner_script()`
- `derot/hook.py:137` `main()`

## Proposed fix

Record the top-level Claude `session_id` in the state file on `SessionStart` (see 012) and have the hook ignore events whose `session_id` differs (except a new `SessionStart` after `/clear` or resume — check `source`).

## Done when

- [x] Test: a second fake claude started inside the pane with the same env doesn't change the row.

## Notes

**2026-10-29:** Hook stores `session_id`; `owns()` ignores events from a different id, except `SessionStart` with source `clear`/`resume`/`compact`. A child `claude` reports source `startup` and is ignored. Remaining edge case: a child started with `--resume`/`--continue` could still take over. Test: `test_006_child_claude_does_not_overwrite_parent` (fails on the old code).
