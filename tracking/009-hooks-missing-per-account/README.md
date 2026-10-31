# Hand-edited accounts silently stay `idle` (hook check is per host, not per account)

| Field | Value |
|---|---|
| Status | done |
| Type | ux |
| Priority | P2 |
| Size | S |
| Verified | reviewer read |
| Source | ccdeck review, 2026-10-29 |

## Problem

The poll only checks that `~/.ccdeck/hook.py` exists on the host. A new account added by editing YAML (`E`) never gets hooks merged into its `settings.json`, and its sessions just sit at `idle` with no hint.

## Where

- `ccdeck/sessions.py:167` `resolve()`
- `ccdeck/tui.py` `reload_config()` (no auto-setup)

## Proposed fix

Poll script also reports which config dirs contain `/.ccdeck/hook.py` in `settings.json` (grep is enough). Show the hint per session; after a YAML reload, run the same background hook install the forms use for new host/account pairs.

## Done when

- [x] Test: add an account by editing YAML → row shows "status hooks not installed for <account>" or hooks get installed automatically.

## Notes

_Add findings, decisions and links to commits here._

## Review (2026-10-31)

**Verdict:** confirmed. **Priority:** P2 (unchanged).

- `resolve()` shows `HOOK_MISSING` only when `~/.ccdeck/hook.py` is missing on the host (`hp.hook`). `reload_config()` → `use_config()` never installs hooks. `forms.new_pairs()` only runs after a form save, and it only looks at new (host, account) pairs, so changing an existing account's `config_dir` in YAML is missed too.
- **Fix, two parts:** (1) In `reload_config()`, call `install_hooks_worker(new_pairs(old, cfg))`, and also include hosts where an account's `config_dir` changed. This is about 3 lines and covers the `E` flow. (2) For the hint, don't pass config dirs into the generic poll script. Use a heuristic instead: `start` already deletes the state file and `SessionStart` writes it right away, so a session that has been running more than ~15 s with no state file means the hooks aren't working. Get the age from `#{session_created}` in `list-sessions` and show "no status from hooks for <account>: press u". This also catches `disableAllHooks`, a broken python3 and edits made outside ccdeck before launch.
- Related to 021, since both are about a hook install that doesn't complete.

## Fix (2026-10-31)

`reload_config()` (after `E`) installs hooks for new host/account-folder pairs; `new_pairs()` now also catches a changed `config_dir`. A session running >15 s with no state file shows "no status from the hooks for account X: press u" (`#{session_created}` + the host's clock). Tests: `test_009_*`.
