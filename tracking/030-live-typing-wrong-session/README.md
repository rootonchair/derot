# Keys typed live can go to the previously typed-into session

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P1 |
| Size | S |
| Verified | confirmed (repro test) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

`queue_input()` starts `input_sender(self.live)` once and the worker keeps looping with that name until the queue is empty. If a send is still in flight (SSH round trip) when you press Ctrl-q, move to another session and press `t`, everything typed into the new session is picked up by the old worker and sent to the *old* session, e.g. `1` or Enter approving a prompt there. An error from the old worker also clears the new session's queue and calls `stop_live()` on it.

## Where

- `ccdeck/tui.py:516` `queue_input()`
- `ccdeck/tui.py:529` `input_sender()`
- `ccdeck/tui.py:497` `stop_live()`

## Proposed fix

Store the target with each queued chunk (`(name, kind, value)`) and send per-target runs, or make `stop_live()`/`action_live()` wait for or drop the old queue and start a fresh sender. On error, only call `stop_live()` if `self.live` is still that session.

## Done when

- [x] `test_030_keys_typed_after_switching_live_session_go_to_the_new_one` passes.

## Notes

Repro: `tests/test_bughunt_new.py::test_030_keys_typed_after_switching_live_session_go_to_the_new_one` (xfail strict).

## Review (2026-10-31)

**Verdict:** confirmed. The test fails with `--runxfail` (`[('a', '1'), ('a', '2')]`). It is deterministic (an event-gated slow send) and tests exactly the stated bug. **Priority:** P1 (unchanged). The window is one in-flight send, but over SSH a send can stall for seconds, and a `1` or Enter going to the wrong session approves a prompt there.

- **Fix:** queue `(name, kind, value)` and have the worker send consecutive runs with the same target. Then `input_sender` takes no argument, and stopping or switching live mode needs no draining. On error, clear only that target's chunks, and call `stop_live()` only if `self.live == name`.
- Fix together with 031 (same function).

## Fix (2026-10-31)

Each queued chunk carries its session; the sender groups by session. Test: `test_030_*`.
