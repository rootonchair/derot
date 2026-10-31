# Codex support

| Field | Value |
|---|---|
| Status | in progress |
| Type | feature |
| Priority | P1 |
| Size | M |
| Verified | tests with a fake Codex; listing checked on real Codex 0.164 sessions |
| Source | user request, 2026-11-01 |

## What

Run OpenAI Codex sessions next to Claude Code ones: an account's `agent: codex` makes its
folder a `CODEX_HOME`; machines get a `codex:` command.

## How (checked against developers.openai.com/codex/hooks and Codex 0.164.0)

- Hooks: same JSON shape as Claude's, in `<CODEX_HOME>/hooks.json`. Events used:
  SessionStart, UserPromptSubmit, PreToolUse, PermissionRequest, PostToolUse, Stop,
  Interrupt (Codex only: → idle "interrupted"), SessionEnd. SessionEnd/Interrupt timeouts
  are capped at 3 s by Codex.
- Trust: Codex runs user hooks only after they're approved in `/hooks` (recorded as
  `[hooks.state."…"] trusted_hash` in config.toml). derot does not write that itself; setup
  says so, and a session with no status after 15 s shows "Codex isn't reporting yet ... /hooks".
  `--dangerously-bypass-hook-trust` exists but bypasses every hook's review, so it isn't used.
- Resume: `codex resume ID` / `codex resume --last` (flags go after `resume`).
- Conversations: `<CODEX_HOME>/sessions/YYYY/MM/DD/rollout-*-<id>.jsonl` (folder from the
  first line's `session_meta.cwd`), titles from `session_index.jsonl` (`thread_name`).
- Login: `codex login`. API key variable: `OPENAI_API_KEY`.

## Done when

- [x] Config, setup (hooks.json), start/resume/login, status, conversation view, resume
      picker and the account form handle Codex; tests in `tests/test_codex.py`.
- [x] Listing and conversation parsing checked on real Codex 0.164 rollouts (read-only).
- [ ] Checked live on a logged-in Codex: hooks approved in `/hooks`, then a prompt →
      approval → done, Esc → interrupted, resume.
