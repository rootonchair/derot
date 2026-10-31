# A paste overtakes text typed just before it

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | confirmed (repro test) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

`input_sender()` walks a batch, runs every `paste` chunk immediately and collects the typed chunks to send afterwards. A batch like `see ` + paste `/tmp/log.txt` + ` please` (typing then Cmd-V while the previous send is in flight) arrives as `/tmp/log.txtsee  please`.

## Where

- `ccdeck/tui.py:537` `input_sender()` batch loop

## Proposed fix

Flush the collected chunks with `send_input()` before each paste (or put `set-buffer`/`paste-buffer` into the same tmux argv in order).

## Done when

- [x] `test_031_paste_keeps_its_place_among_typed_text` passes.

## Notes

Repro: `tests/test_bughunt_new.py::test_031_paste_keeps_its_place_among_typed_text` (xfail strict).

## Review (2026-10-31)

**Verdict:** confirmed. The test fails with `--runxfail` and tests the stated bug (it calls `input_sender` directly with a preset batch, which is a fair way to reach the race). **Priority:** P2 → P3.

- It needs a paste to arrive while an earlier send is still in flight *and* typed text queued in the same batch. That is rare locally and possible over SSH. The garbled text is visible in the live preview before you press Enter.
- **Fix:** best folded into 029: treat paste as a chunk inside `send_input`'s single argv (`set-buffer … ; paste-buffer -p -d …`). Order is then kept for free, and it saves an SSH round trip. Flushing before each paste also works, but costs an extra round trip.

## Fix (2026-10-31)

Pastes go in the same tmux call as typed text, in order (`send_input` kind `paste`). Test: `test_031_*`.
