# Replies starting with `-` are never sent

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P0 |
| Size | S |
| Verified | confirmed (bug-hunt repro: `send-keys: unknown flag -n`) |
| Source | bug-hunt agent, 2026-10-30 |

## Problem

`send-keys -l <text>` reads a leading `-` as a flag. Markdown bullets, options and negative numbers failed, and `--` alone was swallowed silently.

## Fix

`sessions.send_text()` now sends `-l -- <text>`. Test: `test_022_replies_starting_with_dash_are_sent` (fails on the old code with `invalid flag -`).
