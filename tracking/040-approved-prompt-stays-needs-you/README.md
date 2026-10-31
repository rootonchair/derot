# After approving a prompt from ccdeck, the row stays "needs you"

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S |
| Verified | confirmed (test) |
| Source | bug review, 2026-10-31 |

## Problem

No hook fires on approval, so a long approved tool showed "needs you" until it finished (split from 004).

## Where

`ccdeck/sessions.py` `MARK_ANSWERED` / `mark_answered()`; `ccdeck/tui.py` `key_worker`, `queue_input`, `input_sender`; `ccdeck/hook.py` `reconcile()`

## Fix

When ccdeck sends a digit, or Enter / a digit while typing live, to a waiting session, a host-side script flips waiting → busy ("answered, working…") only if the state's `ts` is still the one the console saw. `reconcile()` now also catches a decline while busy. Approvals made while attached are not covered.

## Done when

- [x] Covered by a test.

## Notes

Tests: `test_040_*`.

**2026-10-31, real Claude 2.1.316:** permission prompt → waiting ("wants to use Bash: sleep 15 && …", alert counted); `1` + mark_answered → "answered, working…" at once → "using Bash" → done.
