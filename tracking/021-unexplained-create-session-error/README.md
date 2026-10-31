# Investigate: error when creating a new session (reported by user)

| Field | Value |
|---|---|
| Status | open |
| Type | bug |
| Priority | P2 |
| Size | ? |
| Verified | needs info — not reproduced |
| Source | derot review, 2026-10-29 |

## Problem

The user saw an error creating a session (before logging existed). Config saved fine (`my-project`, account `personal`, plus a new `work` account), but `~/.derot` was never created, so the automatic hook install after saving didn't complete. The same flow works in an isolated environment.

## Where

- `derot/tui.py` `_session_saved()` / `install_hooks_worker()`
- `~/.derot/derot.log` (now available)

## Proposed fix

Ask the user to reproduce with `derot log -f` running; fix based on the logged error.

## Done when

- [ ] Root cause identified and a regression test added.

## Notes

_Add findings, decisions and links to commits here._

## Review (2026-10-31)

**Verdict:** needs info. **Priority:** P1 → P2 (unreproduced, and the flow has changed since).

- Reading `setup_host()`: `~/.derot` is created by `UPLOAD_SCRIPT`, which only runs if `CHECK_SCRIPT` succeeded and `python3=yes`. A missing `claude` does *not* skip it. So the only code paths that leave `~/.derot` missing are: (a) the check failed or timed out (40 s; it runs `$SHELL -lic`, so a slow or interactive-prompting zshrc such as p10k or oh-my-zsh update prompts is the leading suspect), or (b) python3 wasn't found.
- Now that logging exists, ask for `~/.derot/derot.log` lines matching `setup local: ✗` / `can't reach it` / `timed out`. If (a) is the cause, it is the same class of problem as 032 (running the user's interactive login shell), and the fix may be to run the check with `-lc` or `-l` plus a shorter, separate PATH probe.
- Overlaps 009, since both are about a hook install after config changes that doesn't complete.
