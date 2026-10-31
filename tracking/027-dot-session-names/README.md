# Session names starting with `.` never got a status

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S |
| Verified | confirmed by reading |
| Source | bug-hunt agent, 2026-10-30 |

## Problem

`NAME_RE` allowed `.foo`, but the hook ignores `DEROT_SESSION` values starting with `.` and the dump skips dot-files.

## Fix

`NAME_RE` now disallows a leading `.` (`slug()` already stripped it). Test: `test_027_names_cannot_start_with_dot`.
