# No alert for a new prompt or reply that lands between two polls

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S |
| Verified | confirmed (repro test) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

`Notifier.update()` alerts only when the state *name* changes. If you approve a prompt and Claude asks for the next permission before the next poll, the state goes waiting → waiting (new message, newer `ts`) and nothing is announced. The same happens for done → done when a quick turn finishes between polls.

## Where

- `ccdeck/notify.py:126` `Notifier.update()`

## Proposed fix

Remember `(state, ts)` per session and treat a newer `ts` with the same `waiting`/`done` state as a new transition.

## Done when

- [x] `test_035_new_prompt_between_polls_still_alerts` passes; no alert when only an unrelated poll repeats the same `ts`.

## Notes

Repro: `tests/test_bughunt_new.py::test_035_new_prompt_between_polls_still_alerts` (xfail strict).

## Review (2026-10-31)

**Verdict:** confirmed. The test fails with `--runxfail` and is valid. **Priority:** P3 → P2.

- This is the normal flow: approve with `1` → a quick tool runs → the next `PermissionRequest` arrives within one 3 s poll → waiting→waiting, and no alert. That is exactly when the user has turned away after approving. The same goes for a quick done→done turn.
- **Problem with the proposed fix:** using `ts` alone re-alerts falsely. `ts` changes on every hook event, including the `Notification(permission_prompt)` that follows a `PermissionRequest` (state stays waiting, message kept) and `idle_prompt` nudges while done. If those land in different polls you get the duplicates 007 removed. **Better:** have the hook keep an `alert_seq` counter that it increments only when it *enters* an alert-worthy state (`PermissionRequest`, a needs-you `Notification` not suppressed by the "keep PermissionRequest text" branch, `Stop`), and have the Notifier compare `(state, alert_seq)`. Comparing the message as well is a cheaper fallback for older hook files.
- Related to 004 (the approve flow) and 007 (duplicates).

## Fix (2026-10-31)

The hook counts alert-worthy events (`alerts`); the notifier alerts when the count goes up even if the state didn't change. Older hooks (no count) behave as before. Tests: `test_035_*`.
