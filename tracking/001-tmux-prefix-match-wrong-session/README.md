# stop/attach can hit the wrong session (tmux prefix match)

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P0 |
| Size | S |
| Verified | confirmed (reproduced by reviewer, tmux 3.x) |
| Source | derot review, 2026-10-29 |

## Problem

tmux resolves `-t cc-<name>` by exact match, then **prefix**. With `api` stopped and `api-v2` running, `derot stop api` killed `cc-api-v2`. `attach` has the same flaw. The TUI is only protected by status that can be up to one refresh (3 s) old; the CLI is exposed directly.

## Where

- `derot/sessions.py:286` `stop()` — `kill-session -t cc-{name}`
- `derot/sessions.py:299` `attach_argv()`
- `derot/sessions.py:306` `attach()`
- `derot/sessions.py:244` `start_script()` — `set-option -t {target}`

## Proposed fix

Add one helper `tmux_target(name) -> "=cc-<name>:"` (the `=` forces exact match, the trailing `:` stops `.` being read as a pane) and use it for every `-t`. `new-session -s` keeps the bare name.

## Done when

- [x] Test: with `cc-api-v2` running and `cc-api` absent, `derot stop api` fails with "not running" and `cc-api-v2` is still alive.
- [x] Same for `attach`.
- [x] Grep finds no remaining `-t", f"cc-` uses.

## Notes

**2026-10-29:** Added `sessions.target(name)` → `=cc-<name>:` and used it for every `-t` (stop, attach, set-option, has-session). Test: `tests/test_bugfixes.py::test_001_stop_never_hits_a_prefix_match` (fails on the old code).
