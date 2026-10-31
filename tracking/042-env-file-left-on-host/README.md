# API keys stayed on hosts in ~/.derot/env/<name>.sh

| Field | Value |
|---|---|
| Status | done |
| Type | bug/security |
| Priority | P1 |
| Size | S |
| Verified | confirmed (test) |
| Source | bug review, 2026-10-31 |

## Problem

The per-session env file (0600, may hold ANTHROPIC_API_KEY) was never deleted, so keys stayed on every host a session had run on.

## Where

`derot/sessions.py` `env_lines()`, `forget()`

## Fix

The pane reads the env file and deletes it straight away; removing a session also deletes it. Secrets live only in the session's processes.

## Done when

- [x] Covered by a test.

## Notes

Test: `test_sessions.py::test_start_local_and_vm_with_accounts`.
