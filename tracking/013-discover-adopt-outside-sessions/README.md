# Discover and adopt Claude sessions started outside derot

| Field | Value |
|---|---|
| Status | open |
| Type | feature |
| Priority | P0 |
| Size | M |
| Verified | n/a — conflicts with SPEC non-goal (v1); worth revisiting |
| Source | derot review, 2026-10-29 |

## Problem

The user's most repeated ask. Today derot only sees sessions it started.

## Where

- `derot/hook.py:139` exits early when `DEROT_SESSION` is unset
- `derot/sessions.py` `POLL_SCRIPT`

## Proposed fix

1. Hook writes `~/.derot/seen/<session_id>.json` (cwd, state, ts, account dir) when `DEROT_SESSION` is unset — hooks already run for every `claude` using a set-up account, so no daemon.
2. Poll lists `seen/`; show read-only "outside derot" rows (expire after N hours idle or `SessionEnd`).
3. **Adopt**: prefill the new-session form with that folder/account, then "exit it there, then resume `<id>` here" (uses 012).

## Done when

- [ ] Plain fake claude (no `DEROT_SESSION`) appears as an outside row with live state; adopt creates a session that resumes the same id.

## Notes

_Add findings, decisions and links to commits here._
