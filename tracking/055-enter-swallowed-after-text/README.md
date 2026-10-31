# Enter right after typed text didn't submit in real Claude

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P1 |
| Size | S |
| Verified | confirmed on real Claude Code 2.1.316 |
| Source | real-Claude check, 2026-10-31 |

## Problem

Claude Code 2.1.316 reads a long burst of text (81 characters) plus Enter in one write as a paste and swallows the Enter, so the prompt isn't submitted. Typing live over SSH batches exactly like this. Short text (19 characters) was fine; a separate Enter 30 ms later always worked.

## Where

`derot/sessions.py` `send_input()`

## Fix

`_bursts()` sends a key that follows text/paste in its own tmux call, 50 ms later. Verified on real Claude: 82 characters + Enter now submits.

## Done when

- [x] Covered by a test and checked on real Claude.

## Notes

Test: `test_055_key_after_text_goes_in_its_own_burst`. Found in the 2026-10-31 real-Claude check.
