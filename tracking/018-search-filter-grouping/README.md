# Search, filter and grouping

| Field | Value |
|---|---|
| Status | open |
| Type | feature |
| Priority | P2 |
| Size | S–M |
| Verified | n/a |
| Source | ccdeck review, 2026-10-29 |

## Problem

The list gets long with many projects/machines.

## Where

- `ccdeck/tui.py` `render_table()`

## Proposed fix

`/` filters by name/note/dir; `g` cycles grouping (none → project → account → machine) with section rows.

## Done when

- [ ] run_test for filter and grouping.

## Notes

_Add findings, decisions and links to commits here._
