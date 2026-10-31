# Permission alerts said "wants to use Bash" without the command

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | confirmed (test) |
| Source | bug review, 2026-10-31 |

## Problem

`brief()` treated ": " as a sentence end, so "wants to use Bash: rm -rf build" became "wants to use Bash".

## Where

`derot/notify.py` `brief()`

## Fix

Don't split permission messages at the colon.

## Done when

- [x] Covered by a test.

## Notes

Test: `test_035_new_prompt_between_polls_still_alerts`.
