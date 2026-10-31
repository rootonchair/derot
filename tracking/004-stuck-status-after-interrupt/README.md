# Status stuck on working / needs-you after Esc or a denied permission

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S–M |
| Verified | likely (based on Claude Code hook behaviour; not reproduced with real Claude) |
| Source | derot review, 2026-10-29 |

## Problem

Claude Code doesn't fire `Stop` on Esc-interrupt, and denying a permission doesn't fire `PostToolUse`. The row stays `working`, or worse `needs you` pinned at the top, until the next prompt. Also `waiting` is only cleared when an approved tool *finishes*, so a long Bash command shows `needs you` while it runs.

## Where

- `derot/hook.py` `apply()` — event → state table
- `derot/sessions.py` `resolve()`

## Proposed fix

1. Check the installed Claude Code's hook events; if available, also handle `PermissionRequest`/`PostToolUseFailure` (or equivalents) and register them in `installer.EVENTS`.
2. Clear `waiting` on `PreToolUse` of the *next* tool and on `UserPromptSubmit`.
3. Staleness fallback in `resolve()`: `waiting`/`busy` with no hook activity for N seconds → capture the last pane lines; if no permission prompt is visible, show `idle (stale?)`.

## Done when

- [x] Verify against real Claude Code: Esc during a tool run and deny a permission → row leaves `needs you` within one refresh or two. _(event names and transcript markers confirmed from 2.1.312; live run still to do)_
- [x] Fake-claude test for the new events / staleness path.

## Notes

**2026-10-29:** Verified against Claude Code 2.1.312: it has `PermissionRequest`, `PostToolUseFailure` (with `is_interrupt`) and `StopFailure`. Real transcripts confirm the markers: Esc writes a user entry `[Request interrupted by user…]`; a decline writes a `tool_result` with `is_error` and "The user doesn't want to proceed with this tool use".

- Hook handles the three new events (`PermissionRequest` → needs you with "wants to use Bash: <cmd>"; interrupt → idle; `StopFailure` → done with the error). `Stop` uses `last_assistant_message` when present.
- `setup` registers them only where the host's Claude Code contains those names (mmap probe of the resolved binary, ~0.1 s), so older versions keep the 7 core events.
- The poller calls `hook.py --dump`, which runs `reconcile()`: if the transcript changed after the last hook event and ends with an interrupt marker or a declined tool result, the row becomes idle. This covers declines (no hook fires) and older Claude Code.

**Still open:** after you *approve* a long-running tool, the row stays "needs you" until the tool finishes (no event fires on approval). Fixing it would need a pane check (screen scraping); left for later.

Tests: `test_004_*` (decline, Esc, reconcile without the new events), `test_older_claude_gets_only_core_events`.

## Review (2026-10-31)

**Verdict:** confirmed (the remaining part). **Priority:** P0 → P2 (only the remaining part).

- The fixed parts are in the code: `apply()` handles `PermissionRequest`, `PostToolUseFailure(is_interrupt)` and `StopFailure`, and `reconcile()` runs on `--dump` for Esc and declines. Their tests pass.
- Still open: after you approve a permission, no hook event fires, so the row stays at "needs you" until `PostToolUse`. The current hooks docs list no event that fires on approval (`PermissionDenied` covers auto-mode denials only). This happens more often now, because pressing 1-9 or Enter while typing live is the usual way to approve.
- **Simpler fix than screen scraping:** when derot itself sends a digit, or Enter while typing live, to a session in `waiting`, run a small remote script (like `MARK_SEEN`) that changes `waiting` to `busy` ("approved, running…"). Only do it if the state file's `ts` is still the one the console saw. Because the change is stored on the host, `watch` and other consoles see it too, and the `ts` check stops it from overwriting a newer prompt. Approvals made while attached would still need the pane check, or the same flip on detach when the screen shows no prompt.
- **Split:** close 004 and move the "approved long tool still shows needs you" part into a new P2 item. It is related to 035, because the approve-then-next-prompt flow is where alerts get missed.

## Fix (2026-10-31)

Closed: the remaining part (approved prompt stays "needs you") moved to 040 and is fixed there.

**2026-10-31, real Claude 2.1.316:** Esc while Claude was writing → "idle · interrupted" within 0.5 s, and it stayed. The remaining approved-tool part (040) also verified.
