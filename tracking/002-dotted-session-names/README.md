# Session names containing a dot can't be stopped or attached

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P0 |
| Size | S |
| Verified | confirmed (reproduced by reviewer) |
| Source | ccdeck review, 2026-10-29 |

## Problem

Names allow `.` and auto-naming keeps it (folder `next.js-site` → name `next.js-site`). tmux parses `-t cc-next.js-site` as session `cc-next`, pane `js-site` → "can't find pane".

## Where

- `ccdeck/config.py:15` `NAME_RE` allows `.`
- `ccdeck/forms.py:37` `slug()` keeps `.`
- all `-t` targets in `ccdeck/sessions.py` (see 001)

## Proposed fix

Fixed by the `=cc-<name>:` target from 001. Keep `.` allowed in names (spec allows it).

## Done when

- [x] Test: session named `my.app` can start, show status, attach (pty test) and stop.

## Notes

**2026-10-29:** Fixed by the same exact target as 001. Test: `test_002_dotted_names_work` (fails on the old code).
