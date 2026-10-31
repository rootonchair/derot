# Shift/Alt+Enter, Ctrl+arrows and Ctrl+_ never reached the session while typing live

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S |
| Verified | confirmed (test) |
| Source | bug review, 2026-10-31 |

## Problem

`tmux_key()` only mapped a few keys, so a newline in Claude's prompt (shift+enter / alt+enter), word motion and undo were dropped.

## Where

`ccdeck/sessions.py` `tmux_key()`

## Fix

Modifiers on any named key map to tmux `C-`/`M-`/`S-`; shift+enter and alt+enter send `M-Enter` (Claude's newline; plain `S-Enter` would submit).

## Done when

- [x] Covered by a test.

## Notes

Test: `test_preview.py::test_tmux_key_mapping`.

**2026-10-31, real Claude 2.1.316:** `M-Enter` (shift/alt+enter) puts a line break in the prompt box; a trailing `;` survived (029).
