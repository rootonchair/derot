# ccdeck tracking

One subfolder per item; each has a `README.md` with problem, location, proposed fix and
acceptance checks. Update the item's **Status** (`open` → `in progress` → `done` / `wontfix`)
and this table together. Line numbers refer to the code as of 2026-10-29.

| # | Item | Type | Priority | Size | Status |
|---|---|---|---|---|---|
| 001 | [stop/attach can hit the wrong session (tmux prefix match)](001-tmux-prefix-match-wrong-session/README.md) | bug | P0 | S | done |
| 002 | [Session names containing a dot can't be stopped or attached](002-dotted-session-names/README.md) | bug | P0 | S | done |
| 003 | [Starting an already-running session wipes its status](003-duplicate-start-wipes-state/README.md) | bug | P0 | S | done |
| 004 | [Status stuck on working / needs-you after Esc or a denied permission](004-stuck-status-after-interrupt/README.md) | bug | P2 | S–M | done |
| 005 | [API key readable in config file and in `ps`](005-api-key-exposure/README.md) | bug/security | P1 | S | done |
| 006 | [Child `claude` processes overwrite the parent session's status](006-child-claude-leaks-session/README.md) | bug | P1 | S | done |
| 007 | [Duplicate / unnecessary notifications](007-duplicate-notifications/README.md) | ux | P1 | S | done |
| 008 | [`/Users/<me>/.claude` isn't treated as the default account folder](008-absolute-default-config-dir/README.md) | ux/bug | P1 | S | done |
| 009 | [Hand-edited accounts silently stay `idle` (hook check is per host, not per account)](009-hooks-missing-per-account/README.md) | ux | P2 | S | done |
| 010 | [Removing a session leaves its state file; re-adding the name shows old data](010-remove-leaves-stale-state/README.md) | ux | P3 | S | done |
| 011 | [Remote project folder isn't checked until you attach](011-remote-dir-not-validated/README.md) | ux | P3 | S | done |
| 012 | [Pick which conversation to resume (and make `c` resume the right one)](012-resume-specific-conversation/README.md) | feature | P0 | M | done |
| 013 | [Discover and adopt Claude sessions started outside ccdeck](013-discover-adopt-outside-sessions/README.md) | feature | P0 | M | open |
| 014 | [Approve or reply without attaching](014-quick-reply-approve/README.md) | feature | P1 | S | done |
| 015 | [Live preview of the selected session's screen](015-live-pane-preview/README.md) | feature | P1 | S–M | done |
| 016 | [`watch` as a background service (launchd), no duplicate alerts](016-watch-launchd-service/README.md) | feature | P1 | S | open |
| 017 | [Token usage and estimated cost per session and account](017-usage-cost/README.md) | feature | P2 | M | open |
| 018 | [Search, filter and grouping](018-search-filter-grouping/README.md) | feature | P2 | S–M | open |
| 019 | [Bulk actions (multi-select stop / continue)](019-bulk-actions/README.md) | feature | P2 | S | open |
| 020 | [Mark seen without attaching; expire old `done` rows](020-mark-seen-expire-done/README.md) | feature | P2 | S | open |
| 021 | [Investigate: error when creating a new session (reported by user)](021-unexplained-create-session-error/README.md) | bug | P2 | ? | open |
| 022 | [Replies starting with `-` are never sent](022-reply-starting-with-dash/README.md) | bug | P0 | S | done |
| 023 | [`$HOME/...` in `config_dir`/`dir` reached Claude as a literal relative path](023-dollar-home-paths/README.md) | bug | P1 | S | done |
| 024 | [Attach fails completely on tmux < 2.9 (no `window-size`)](024-attach-old-tmux/README.md) | bug | P1 | S | done |
| 025 | [An idle reminder overwrote a pending permission prompt](025-idle-reminder-hides-prompt/README.md) | bug | P1 | S | done |
| 026 | [Starting while a host is offline re-announced old "needs you"](026-offline-start-realert/README.md) | bug | P2 | S | done |
| 027 | [Session names starting with `.` never got a status](027-dot-session-names/README.md) | bug | P2 | S | done |
| 028 | [Preview stopped refitting after an outside attach or restart](028-preview-size-cache-stale/README.md) | bug | P2 | S | done |
| 029 | [Semicolons typed live or pasted are dropped](029-typed-semicolons-dropped/README.md) | bug | P0 | S | done |
| 030 | [Keys typed live can go to the previously typed-into session](030-live-typing-wrong-session/README.md) | bug | P1 | S | done |
| 031 | [A paste overtakes text typed just before it](031-paste-overtakes-typed-text/README.md) | bug | P3 | S | done |
| 032 | [Sessions can't start when the login shell isn't POSIX (fish, csh)](032-non-posix-login-shell/README.md) | bug | P2 | M | done |
| 033 | [`setup` replaces a symlinked settings.json with a plain file](033-setup-breaks-symlinked-settings/README.md) | bug | P3 | S | done |
| 034 | [Ctrl-P while typing live opens the command palette](034-ctrl-p-ends-live-typing/README.md) | bug | P3 | S | done |
| 035 | [No alert for a new prompt or reply that lands between two polls](035-missed-repeat-alerts/README.md) | bug | P2 | S | done |
| 036 | [Auto-compaction mid-turn shows a working session as idle](036-compaction-flips-busy-to-idle/README.md) | bug | P3 | S | done |
| 037 | [Informational notifications are shown as "needs you"](037-informational-notification-needs-you/README.md) | bug | P2 | S | done |
| 038 | [`refresh: .inf` is accepted, then every save crashes](038-infinite-refresh-crashes-save/README.md) | bug | P3 | S | done |
| 039 | [`watch` lock isn't atomic and survives SIGTERM](039-watch-lock-race-stale/README.md) | bug | P3 | S | done |
| 040 | [After approving a prompt from ccdeck, the row stays "needs you"](040-approved-prompt-stays-needs-you/README.md) | bug | P2 | S | done |
| 041 | [Shift/Alt+Enter, Ctrl+arrows and Ctrl+_ never reached the session while typing live](041-live-keys-dropped/README.md) | bug | P2 | S | done |
| 042 | [API keys stayed on hosts in ~/.ccdeck/env/<name>.sh](042-env-file-left-on-host/README.md) | bug/security | P1 | S | done |
| 043 | [Every ssh call fails when a VM account's login shell is csh/tcsh](043-remote-csh-login-shell/README.md) | bug | P3 | M | open |
| 044 | [Permission alerts said "wants to use Bash" without the command](044-permission-alert-drops-command/README.md) | bug | P3 | S | done |
| 045 | [A new account's session stayed "idle" forever (hook setup interrupted)](045-new-account-stays-idle/README.md) | bug | P1 | S | done |
| 046 | [A hook.py cut off by an interrupted setup counted as installed](046-cut-off-hook-never-repaired/README.md) | bug | P2 | S | done |
| 047 | [Hosts kept an older hook.py until `ccdeck setup` was re-run](047-old-hook-on-hosts/README.md) | bug | P2 | S | done |
| 048 | [A timed-out command left its children running](048-timeout-leaves-children/README.md) | bug | P3 | S | done |
| 049 | [A failed start left the account's env file (API key) on the host](049-env-file-after-failed-start/README.md) | bug/security | P2 | S | done |
| 050 | [`ccdeck watch` poll errors only went to stderr](050-watch-errors-not-logged/README.md) | bug | P3 | S | done |
| 051 | [Quitting the console silently waits for background workers](051-quit-waits-for-workers/README.md) | ux/bug | P3 | S–M | open |
| 052 | [Preview resizing leaves sessions at the preview's size after the console quits](052-preview-fit-sticks-after-exit/README.md) | bug | P3 | S | open |
| 053 | [Toasts raised while attached or logging in may expire unseen (suspected)](053-toasts-expire-while-suspended/README.md) | ux | P3 | S | open |
| 054 | [One-time backups can be left cut off forever (suspected)](054-one-time-backups-not-atomic/README.md) | bug | P3 | S | open |
| 055 | [Enter right after typed text didn't submit in real Claude](055-enter-swallowed-after-text/README.md) | bug | P1 | S | done |
| 056 | [Trust / login / first-run screens showed as "idle"](056-pre-start-dialogs-show-idle/README.md) | bug | P2 | S | done |

## Suggested order

1. **001–004**: P0 bug fixes (wrong-session kill, dotted names, wiped status, stuck status)
2. **012**: resume a specific conversation (stores `session_id`; base for 006 and 013)
3. **013**: discover/adopt outside sessions (revisits a SPEC non-goal)
4. **021**: waiting on a reproduction with `ccdeck log -f`
5. P1s: 005, 007, 014, 015, 016, 006, 008; then P2s.

## Reference designs

- ai-devkit `agent console` (github.com/codeaholicguy/ai-devkit): Ink TUI, agent list plus transcript preview plus message box, `o` focuses the agent's real terminal tab (tmux/iTerm2/Ghostty/WezTerm). Basis for 014/015.

## New items

Copy any item folder, take the next number, and add a row above.
