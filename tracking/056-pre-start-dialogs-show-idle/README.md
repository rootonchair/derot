# Trust / login / first-run screens showed as "idle"

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S |
| Verified | confirmed on real Claude Code 2.1.316 |
| Source | real-Claude check, 2026-10-31 |

## Problem

Before a session really starts, Claude can wait on a screen that fires no hook: "Is this a project you trust?" in a new folder, or a new account's welcome / login screens. derot showed "idle" (and after 15 s suggested pressing u, which was wrong advice).

## Where

`derot/sessions.py` `resolve()`

## Fix

A running session with no state file after 15 s is "needs you": "Claude hasn't started yet, probably a login, trust or first-run screen (i or click to answer it; if nothing's there, press u)". Verified on the real `work-app` (new account, not logged in).

## Done when

- [x] Covered by a test and checked on real Claude.

## Notes

Test: `test_009_running_without_status_says_so`. Found in the 2026-10-31 real-Claude check.
