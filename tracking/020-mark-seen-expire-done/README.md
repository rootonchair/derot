# Mark seen without attaching; expire old `done` rows

| Field | Value |
|---|---|
| Status | open |
| Type | feature |
| Priority | P2 |
| Size | S |
| Verified | n/a |
| Source | ccdeck review, 2026-10-29 |

## Problem

`done` rows stay pinned near the top until you attach.

## Where

- `ccdeck/sessions.py` `mark_seen()`
- `ccdeck/tui.py`

## Proposed fix

`m` marks the selected session seen (done → idle). Optional config `done_expiry` (e.g. 2h) auto-demotes in `resolve()`.

## Done when

- [ ] Tests for both.

## Notes

_Add findings, decisions and links to commits here._
