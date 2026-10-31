# Starting while a host is offline re-announced old "needs you"

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S |
| Verified | confirmed (bug-hunt repro) |
| Source | bug-hunt agent, 2026-10-30 |

## Problem

Sessions first seen offline were recorded as `offline`. When the host came back, an already-waiting session counted as a change and alerted.

## Fix

The notifier treats a session's first state seen online as the baseline, which also covers sessions newly added to the config. Test: `test_026_no_alert_for_state_first_seen_after_offline_start` (fails on the old code).
