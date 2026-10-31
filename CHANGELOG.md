# Changelog

## 0.1.1 (2026-11-01)

- README: images and links use full URLs, so the screenshots show on PyPI.

## 0.1.0 (2026-11-01)

First public version.

- Codex support: accounts with `agent: codex` run OpenAI Codex (`CODEX_HOME`) next to Claude
  Code, with status from Codex hooks (`hooks.json`, approved once in `/hooks`), the resume
  picker and `c` (`codex resume`), the conversation view and `codex login`.

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
