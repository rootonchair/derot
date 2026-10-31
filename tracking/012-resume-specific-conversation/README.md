# Pick which conversation to resume (and make `c` resume the right one)

| Field | Value |
|---|---|
| Status | done |
| Type | feature |
| Priority | P0 |
| Size | M |
| Verified | n/a |
| Source | derot review, 2026-10-29 |

## Problem

`c` uses `--continue`, which resumes the newest conversation in that folder — wrong if the user also ran `claude` there elsewhere. The user asked how to resume a specific conversation.

## Where

- `derot/hook.py` (doesn't store `session_id`)
- `derot/tui.py:310` `action_continue()`
- `derot/sessions.py` `start()`

## Proposed fix

1. Hook stores `session_id` in the state file.
2. `sessions.list_conversations(host, account, dir)`: remote `python3 -c` that reads `<config_dir>/projects/<encoded-dir>/*.jsonl`, returns id, mtime, first/last user prompt, message count.
3. `R` opens a modal list; start with `--resume <id>`.
4. `c` prefers the stored `session_id`, falls back to `--continue`.

## Done when

- [x] Fake claude writes transcripts in the real layout; test listing + `--resume <id>` reaches the fake.
- [x] Manual check against real Claude Code's `projects/` folder naming.

## Notes

_Add findings, decisions and links to commits here._

## Fix (2026-10-31)

- `sessions.conversations()` runs `CONVERSATIONS_SCRIPT` on the host: reads `<config_dir>/projects/<folder with non-alphanumerics as ->/*.jsonl` (checked against the real layout: `model_test` → `model-test`), newest first. Title = last `custom-title`, else last `ai-title`; plus first user prompt and last `last-prompt`. Titles are found by searching backwards with mmap (real transcripts are ~10 MB). Conversations where nothing was said are skipped.
- `R` opens `forms.ResumePicker` (marks the conversation this session last used); Enter starts it with `--resume <id>`, in the background like `s`/`c`.
- `c` resumes the session's stored `session_id`; if its transcript doesn't exist (nothing was said), it falls back to `--continue`.
- CLI: `derot start NAME --resume ID`, `derot history NAME`.
- Found and fixed while testing: after a quick stop → start, the killed Claude's late `SessionEnd` could claim the fresh state file, so the new session's events were all ignored. `hook.owns()` no longer lets `SessionEnd` claim an empty state.
- Tests: `tests/test_resume.py` (fake Claude now writes transcripts in the real layout and honours `--resume` / `--continue`).

**2026-10-31, real Claude 2.1.316:** listing showed the real conversation (ai-title, first and last prompt); the stored id was the newest; the `c` path reopened it with the earlier messages and the same session id.
