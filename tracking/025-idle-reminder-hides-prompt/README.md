# An idle reminder overwrote a pending permission prompt

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P1 |
| Size | S |
| Verified | suspected (bug hunt; verified with `apply()`) |
| Source | bug-hunt agent, 2026-10-30 |

## Problem

A `Notification` with `idle_prompt` ("waiting for your input") turned `waiting` into `idle`, so the row dropped out of "needs you" while the dialog was still open.

## Fix

The idle reminder now keeps both `done` and `waiting`. Test: `test_025_idle_reminder_keeps_pending_prompt` (fails on the old code). Not changed: Pre/PostToolUse from parallel subagents in the same session can still turn `waiting` into `busy`, because they share a session_id and can't be told apart.
