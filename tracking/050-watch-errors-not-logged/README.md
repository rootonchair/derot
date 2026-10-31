# `ccdeck watch` poll errors only went to stderr

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | confirmed (test) |
| Source | bug hunt after 045, 2026-10-31 |

## Problem

As a background service, watch's stderr is usually unread. Poll exceptions and failed config reloads left no trace in `ccdeck log`.

## Where

`ccdeck/cli.py` `cmd_watch()` (line 170)

## Fix

Both are logged too, the poll failure with its traceback.

## Done when

- [x] Covered by a test.

## Notes

Test: `test_bughunt_new.py::test_050_watch_logs_poll_failures`.
