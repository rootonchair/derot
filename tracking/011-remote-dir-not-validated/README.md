# Remote project folder isn't checked until you attach

| Field | Value |
|---|---|
| Status | done |
| Type | ux |
| Priority | P3 |
| Size | S |
| Verified | reviewer read |
| Source | derot review, 2026-10-29 |

## Problem

The form checks only local folders. A typo in a VM path is discovered only after starting and attaching (pane shows "folder not found").

## Where

- `derot/forms.py:200` `SessionForm.action_save()`

## Proposed fix

On save for a remote host, run `test -d <qpath>` over SSH in a worker; if missing, show a warning toast (don't block — host may be offline).

## Done when

- [x] Test with fake ssh: missing remote dir → warning toast; existing → none.

## Notes

_Add findings, decisions and links to commits here._

## Review (2026-10-31)

**Verdict:** confirmed (the code does what the item says), but the impact is now lower. **Priority:** P2 → P3.

- `SessionForm.action_save()` still checks only local folders. But "only discovered after attaching" no longer holds: the auto preview shows the screen of a running session, so `[derot] folder not found: …` is visible as soon as you start it. The row does show `idle` (no hook fires), which is misleading.
- **Better fix:** check at *start* instead of, or as well as, at save. In `start_script()`, add `[ -d <qpath dir> ] || { echo "folder not found: <dir>" >&2; exit 1; }` before `new-session`. `start()` then raises a clear `SessionError` toast, no dead pane is left behind, and it also catches folders deleted after saving. It works offline-safely because the start needs the host anyway. A save-time SSH check can be added later as a non-blocking toast.
- **Missing:** the *local* check runs `os.path.expanduser(d)` on the raw input, so `$HOME/proj` (supported by 023 via `norm_path`) is rejected with "Folder not found on this Mac". Run `config.norm_path()` before the `isdir` check.

## Fix (2026-10-31)

`start_script` checks the folder before creating the session: `start` fails with "folder not found: …" (also for VMs). The session form accepts `$HOME/…` (saved as `~/…`). Tests: `test_sessions.py::test_missing_dir_fails_the_start`, `test_forms.py::test_session_form_validates`.
