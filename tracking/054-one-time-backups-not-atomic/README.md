# One-time backups can be left cut off forever

| Field | Value |
|---|---|
| Status | open |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | suspected |
| Source | bug hunt after 045, 2026-10-31 |

## Problem

`config.yaml.bak` and `settings.json.ccdeck-bak` are written in place, and only if they don't exist yet. If that write is interrupted, the cut-off backup is kept and never rewritten. The real files themselves are written atomically.

## Where

`ccdeck/config.py` `save()` (line 287), `ccdeck/installer.py` `MERGE_SCRIPT` (line 81)

## Fix (proposed)

Copy to a temp file next to it, then `os.replace`.

## Done when

- [ ] Backups are written atomically.
