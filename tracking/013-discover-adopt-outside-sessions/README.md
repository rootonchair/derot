# Discover and adopt Claude sessions started outside ccdeck

| Field | Value |
|---|---|
| Status | open |
| Type | feature |
| Priority | P0 |
| Size | M |
| Verified | n/a — conflicts with SPEC non-goal (v1); worth revisiting |
| Source | ccdeck review, 2026-10-29 |

## Problem

The user's most repeated ask. Today ccdeck only sees sessions it started.

## Where

- `ccdeck/hook.py:139` exits early when `CCDECK_SESSION` is unset
- `ccdeck/sessions.py` `POLL_SCRIPT`

## Proposed fix

1. Hook writes `~/.ccdeck/seen/<session_id>.json` (cwd, state, ts, account dir) when `CCDECK_SESSION` is unset — hooks already run for every `claude` using a set-up account, so no daemon.
2. Poll lists `seen/`; show read-only "outside ccdeck" rows (expire after N hours idle or `SessionEnd`).
3. **Adopt**: prefill the new-session form with that folder/account, then "exit it there, then resume `<id>` here" (uses 012).

## Done when

- [ ] Plain fake claude (no `CCDECK_SESSION`) appears as an outside row with live state; adopt creates a session that resumes the same id.

## Notes

_Add findings, decisions and links to commits here._
