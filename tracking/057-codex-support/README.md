# Codex support

| Field | Value |
|---|---|
| Status | done |
| Type | feature |
| Priority | P1 |
| Size | M |
| Verified | tests with a fake Codex; checked live on Codex 0.164.0 |
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
- [x] Checked live on a logged-in Codex: hooks approved in `/hooks`, then a prompt →
      approval → done, Esc → interrupted, resume.

## Live check (2026-11-01, Codex 0.164.0, real ~/.codex)

- Codex found derot's 8 hooks in `hooks.json` and asked for review; after `t` (trust all)
  in `/hooks` all were active, recorded as `[hooks.state."<hooks.json>:<event>:0:0"]
  trusted_hash` in config.toml. The hash covers the hook entry (command), not hook.py, so
  derot updates don't need re-approval unless the entries change.
- Prompt → working → "using Bash" → done, with the reply as the message.
- With "Ask for approval" permissions: PermissionRequest → needs you ("wants to use Bash:
  touch …"); `1` + mark_answered → "answered, working…" → done.
- Esc while working → Interrupt → idle "interrupted".
- Listing showed the real conversation (thread title, first and last prompt); the stored id
  matched; `codex resume <id>` reopened it with the same session id.
- Findings, fixed: Codex sends **no SessionStart at launch** (fresh: it comes with the first
  prompt; resume: none), so "no status after 15 s = needs you" was wrong for Codex. Now a
  silent Codex session is idle unless the hooks aren't approved (read from config.toml).
  Codex's own "update available" prompt can also appear before a session starts.

## Login (2026-11-01)

- Login is per profile: `codex login status` → "Not logged in" (exit 1) for an empty
  CODEX_HOME, "Logged in using ChatGPT" (exit 0) for a real one; credentials in `auth.json`.
- Codex **ignores OPENAI_API_KEY in the environment** (0.164 shows its sign-in screen), so
  derot pipes an account's key into `codex login --with-api-key` before starting (checked on
  real Codex with a dummy key: "API key configured", no sign-in screen; nothing was sent).
- On SSH machines `l` runs `codex login --device-auth` (the browser flow calls back to
  localhost).
- A profile with no `auth.json` (and no keychain store configured, no API key) shows "needs
  you: Codex isn't logged in for account X: press l".

