# Preview stopped refitting after an outside attach or restart

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S |
| Verified | suspected (bug hunt) |
| Source | bug-hunt agent, 2026-10-30 |

## Problem

`_fitted` cached the fitted size even when `fit` failed, and was only cleared by the console's own attach.

## Fix

Removed the cache. `sessions.screen()` returns the window size along with the capture (one tmux call), and the console refits whenever it differs and nobody is attached. Test: `test_028_preview_refits_after_outside_resize`.
