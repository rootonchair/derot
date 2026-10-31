# Bulk actions (multi-select stop / continue)

| Field | Value |
|---|---|
| Status | open |
| Type | feature |
| Priority | P2 |
| Size | S |
| Verified | n/a |
| Source | ccdeck review, 2026-10-29 |

## Problem

After a reboot, every session has to be continued one by one.

## Where

- `ccdeck/tui.py`

## Proposed fix

Space toggles selection; `x`/`c` apply to the selection (with one confirmation).

## Done when

- [ ] run_test: select 3 stopped → `c` starts all.

## Notes

_Add findings, decisions and links to commits here._
