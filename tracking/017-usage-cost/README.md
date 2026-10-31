# Token usage and estimated cost per session and account

| Field | Value |
|---|---|
| Status | open |
| Type | feature |
| Priority | P2 |
| Size | M |
| Verified | n/a |
| Source | ccdeck review, 2026-10-29 |

## Problem

No visibility into how much each session/account is spending.

## Where

- `ccdeck/hook.py` `Stop` handling
- `ccdeck/tui.py` table/summary

## Proposed fix

On `Stop`, sum `message.usage` from transcript lines added since the last offset (store offset in state). Show tokens / est. $ column and per-account totals in the summary.

## Done when

- [ ] Fake transcript with usage blocks → correct totals.

## Notes

_Add findings, decisions and links to commits here._
