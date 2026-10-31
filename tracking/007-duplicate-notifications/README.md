# Duplicate / unnecessary notifications

| Field | Value |
|---|---|
| Status | done |
| Type | ux |
| Priority | P1 |
| Size | S |
| Verified | reviewer read |
| Source | ccdeck review, 2026-10-29 |

## Problem

Running the console and `ccdeck watch` together sends every alert twice. Alerts fire even for the session you're attached to. A host coming back online re-sends `needs you` for sessions that were already waiting before it dropped.

## Where

- `ccdeck/notify.py:52` `Notifier.update()`
- `ccdeck/notify.py:72` `_alert()`

## Proposed fix

1. Lock file `~/.ccdeck/notifier.lock` (pid): only one notifier active; the TUI shows toasts but skips desktop alerts while `watch` holds the lock.
2. Skip alerts when `st.attached`.
3. Treat `offline → X` as no transition (keep the pre-offline state as `prev`).

## Done when

- [x] Tests for each of the three rules.

## Notes

**2026-10-29:** - No alert for attached sessions.
- `offline` isn't a state for alerting: when a host returns, sessions are compared with their pre-offline state.
- `ccdeck watch` takes `~/.ccdeck/watch.pid`; a second watch refuses to start; the console (`defer_to_watch=True`) still shows toasts but leaves desktop alerts to watch while it runs.

Tests: `test_007_*`.
