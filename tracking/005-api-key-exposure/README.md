# API key readable in config file and in `ps`

| Field | Value |
|---|---|
| Status | done |
| Type | bug/security |
| Priority | P1 |
| Size | S |
| Verified | likely (reviewer read the code) |
| Source | derot review, 2026-10-29 |

## Problem

Account `env` (e.g. `ANTHROPIC_API_KEY`) is stored in plain text in `config.yaml`, written with the default umask (usually readable by every user). The key is also embedded in the pane's command line (`export K=V` inside `-lic '...'`), so `ps` on that machine shows it.

## Where

- `derot/config.py:272` `save()` — `tmp.write_text` without mode
- `derot/sessions.py:216` `env_lines()`
- `derot/sessions.py:224` `inner_script()`

## Proposed fix

1. Write config with mode 0600 (`os.open(..., 0o600)`), and chmod on save.
2. Write account env to `~/.derot/env/<account>.sh` (0600) on the host during start/setup and `. file` it in the pane instead of putting values on the command line.
3. Optional: macOS Keychain for local keys.

## Done when

- [x] `stat` shows 0600 for config and env files.
- [x] `ps -o args` for the pane has no key.
- [x] Log redaction test still passes.

## Notes

**2026-10-29:** - Config written with mode 0600 (save, init, and the `.bak`).
- Account env goes to `~/.derot/env/<session>.sh` (0600, written from stdin inside a `umask 077` subshell so panes keep the normal umask) and is sourced by the pane; `login` uses `_login.sh`. No values on any command line.
- Not done: macOS Keychain (optional).

Tests: `test_start_local_and_vm_with_accounts` (env reaches claude, file is 0600, value not in the start script or pane command), `test_005_config_is_private`.
