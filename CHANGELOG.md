# Changelog

## 0.1.0 (unreleased)

First public version.

- One console for Claude Code sessions across projects, accounts (`CLAUDE_CONFIG_DIR`)
  and machines (this computer or any SSH host), each in its own tmux session.
- Live status from Claude Code hooks: needs you, done, working, idle, stopped, offline.
- Right-hand panel: session details and a live preview of Claude's own screen; type into
  a session from there (Enter or click), answer prompts with `1`–`9`, or go full screen
  (`f`).
- Resume picker (`R`) for past conversations; `c` continues the session's own last one.
- Forms for sessions, machines and accounts, with folder suggestions (also over SSH) and
  SSH targets from `~/.ssh/config`.
- Desktop notifications when a session needs you (optionally when one finishes);
  `derot watch` for alerts without the console.
- CLI: `init`, `setup`, `ls`, `start` (`-c`, `--resume`), `history`, `attach`, `stop`,
  `watch`, `log`, `login`.
