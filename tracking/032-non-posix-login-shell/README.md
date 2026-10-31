# Sessions can't start when the login shell isn't POSIX (fish, csh)

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | M |
| Verified | suspected (code reading; fish not installed here) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

The pane runs `"${SHELL:-/bin/sh}" -lic '<script>'`, and the script is POSIX sh: `unset`, bare `derot_dir=...` assignments, `if [ ... ]; then ... fi`, `${derot_dir%/}`, `code=$?`. With `SHELL=/usr/local/bin/fish` (or csh/tcsh/nu) on the Mac or a VM, these are syntax errors, so `start`, `login` and the `claude` check in `setup` (`c=$0; case $c in ...`) all fail.

## Where

- `derot/sessions.py:264` `pane_cmd()` / `inner_script()`
- `derot/sessions.py:369` `login()`
- `derot/installer.py:27` `CHECK_SCRIPT`

## Proposed fix

Use the login shell only to get the user's PATH, and run the POSIX part with `/bin/sh`: write the script next to the env file and start `"$SHELL" -lic 'exec /bin/sh ~/.derot/run/<name>.sh'` (that string parses the same in sh, bash, zsh, fish and csh). Same for the setup check.

## Done when

- [x] A test with `SHELL` pointing at a non-POSIX shim (e.g. one that rejects `if [`) starts a session and passes the claude check.

## Notes

_Add findings, decisions and links to commits here._

## Review (2026-10-31)

**Verdict:** confirmed (no longer only suspected). **Priority:** P2 (unchanged): fatal for affected users, but few users have it.

- Reproduced with `/bin/tcsh` as `SHELL` on an isolated tmux socket, using `pane_cmd()` with `claude: /bin/echo`: `Bad : modifier in $ '-'.` / `derot_dir=…: Command not found.` / `Missing '}'.`
- **The item misses a layer:** tmux runs the pane command through its `default-shell -c`, and `default-shell` defaults to `$SHELL` (checked with a logging shim: `fsh -c <cmd>`). So the *outer* `"${SHELL:-/bin/sh}" -lic '…'` is already parsed by fish or csh, and in fish `${…}` is a syntax error. The proposed outer string `"$SHELL" -lic 'exec /bin/sh <file>'` parses in all of these shells, so the fix holds. Simpler and more robust: also `set-option -g default-shell /bin/sh` on the derot server (it is a private `-L derot` server, so this is safe), or start the pane with an argv of `/bin/sh -c …`.
- **Remote hosts:** `remote.wrap()` sends `shlex.join(argv)` to ssh, and that string is parsed by the remote account's *passwd* shell. csh and tcsh reject multi-line single-quoted strings, and `!` triggers history expansion, so with a csh login shell on a VM every `remote.sh` and `remote.python` call (poll, start, setup) fails and the host shows as offline. fish handles `shlex` quoting, except that `\\` and `\'` are escapes inside its single quotes. A full fix should send scripts over stdin (`sh -s`) or base64-encode them. That can be a separate item (P3).
- Related to 021 suspect (a): `-lic` runs the user's interactive rc files for the PATH probe.

## Fix (2026-10-31)

Panes run under `/bin/sh` (`default-shell` on the private server) and start a stored script via `launch_cmd`: bash/zsh/ksh source it (aliases keep working), other shells `exec /bin/sh` it. The setup check only asks the login shell for `env`. Tests: `test_032_*` (tcsh, zsh, bash; fails on the old code). Remote csh login shells (ssh quoting) are split into 043.
