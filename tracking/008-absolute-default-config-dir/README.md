# `/Users/<me>/.claude` isn't treated as the default account folder

| Field | Value |
|---|---|
| Status | done |
| Type | ux/bug |
| Priority | P1 |
| Size | S |
| Verified | reviewer read |
| Source | derot review, 2026-10-29 |

## Problem

Only `~/.claude` and `$HOME/.claude` count as default. An absolute path makes derot export `CLAUDE_CONFIG_DIR`, and on macOS Claude Code then likely looks logged out (keychain entry is tied to the default).

## Where

- `derot/config.py:46` `Account.is_default_dir`

## Proposed fix

Normalise in the form and on load: if `expanduser(config_dir)` equals `expanduser('~/.claude')` (local) store `~/.claude`. For remote hosts, decide in the pane script (`[ "$dir" = "$HOME/.claude" ]`).

## Done when

- [x] Test: account with `/Users/x/.claude` (HOME=/Users/x) → no `CLAUDE_CONFIG_DIR` export.

## Notes

**2026-10-29:** The pane decides on the host: `if [ "${dir%/}" = "$HOME/.claude" ]` → leave `CLAUDE_CONFIG_DIR` unset, so any spelling of the default folder works locally and on VMs. `Account.is_default_dir` also compares expanded paths. Test: `test_008_absolute_default_folder_keeps_normal_login`.
