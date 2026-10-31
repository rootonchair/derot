# A hook.py cut off by an interrupted setup counted as installed

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S |
| Verified | confirmed (test) |
| Source | bug hunt after 045, 2026-10-31 |

## Problem

The upload wrote `~/.ccdeck/hook.py` in place (`cat > hook.py`). If setup was interrupted mid-upload (console quit or Ctrl-C), half a file stayed. The check before a start (045) only tested that the file existed, so it never repaired it. Every hook call then failed with a SyntaxError, and the session stayed idle with no visible error. Hooks firing during an upload could also read a half-written file.

## Where

`ccdeck/installer.py` `UPLOAD_SCRIPT` (line 52), `HOOKS_PRESENT_SCRIPT` / `hooks_present()` (lines 153–188)

## Fix

The upload writes a temp file next to hook.py and renames it over the old one. `hooks_present()` compares the host's hook.py with this version's sha256, so a cut-off file is set up again before the next start.

## Done when

- [x] Covered by a test.

## Notes

Tests: `test_bughunt_new.py::test_046_*`.
