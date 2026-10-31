# Auto-compaction mid-turn shows a working session as idle

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | suspected (apply() behaviour confirmed by test; mid-turn SessionStart is from the Claude Code docs) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

`apply()` sets `idle` on every `SessionStart`. Claude Code fires `SessionStart` with `source: compact` after auto-compaction, which can happen in the middle of a turn, so the row shows `idle` while Claude keeps working until the next tool event.

## Where

- `ccdeck/hook.py:133` `apply()` SessionStart branch

## Proposed fix

For `source == "compact"`, keep the current state (only refresh `session_id`/`transcript_path`).

## Done when

- [x] `test_036_compaction_mid_turn_keeps_busy` passes.

## Notes

Repro: `tests/test_bughunt_new.py::test_036_compaction_mid_turn_keeps_busy` (xfail strict).

## Review (2026-10-31)

**Verdict:** confirmed (the docs back it up). **Priority:** P3 (unchanged).

- The hooks docs (code.claude.com/docs/en/hooks) list SessionStart `compact` as "Auto or manual compaction", and there are also `PreCompact` (`manual`/`auto`) and `PostCompact` events. Auto-compaction happens when the context fills, which can be mid-turn. `apply()` then sets `idle` until the next PreToolUse/Stop, usually a few seconds. Worst case: compaction just before the final answer leaves it `idle` until `Stop`. The test tests `apply()` directly, which is the right unit.
- **Fix:** sound. Keep the state for `source == "compact"` and only update `session_id`/`transcript_path` (`main()` already does that for every event). After a manual `/compact` from `done`, the row stays `done`, which is fine.

## Fix (2026-10-31)

SessionStart `compact` keeps the current state. Test: `test_036_*`.
