# Approve or reply without attaching

| Field | Value |
|---|---|
| Status | done |
| Type | feature |
| Priority | P1 |
| Size | S |
| Verified | n/a |
| Source | ccdeck review, 2026-10-29 |

## Problem

Clearing a `needs you` row requires attach → answer → Ctrl-q.

## Where

- new action in `ccdeck/tui.py`
- `ccdeck/sessions.py` new `send_keys()`

## Proposed fix

`a` (approve) sends `1`/Enter; `y` opens a one-line input and sends text + Enter, via `tmux send-keys -t '=cc-x:'` through `remote.run`. Show the pane preview (015) before sending.

## Done when

- [x] Fake claude: approving from the console (reply box) reaches `done` without attaching.
- [ ] Real Claude Code: number keys pick permission options.

## Notes

**2026-10-30:** Reply box under the preview (`i`): text is sent with `tmux send-keys -l` plus Enter. An empty Enter just presses Enter, accepting the highlighted option. Digits `1`–`9` go to a session that needs you, and only when the list is focused. Tests: `tests/test_preview.py` (fake Claude driven entirely from the reply box, digit routing). **To verify with real Claude Code:** that number keys pick options in its permission prompt.

**2026-10-31:** Removed the reply box (`i`) in favour of live typing (`t`, see 015), which does everything it did and also shows Claude's own UI (slash menus, pickers, suggestions) as you type. Kept: `1`–`9` on the list for one-keystroke answers to a prompt. `sessions.send_text` was removed; `send_input` (with `-l --`) covers it.


**2026-10-31:** Live typing moved from `t` to `i` (user preference).

**2026-10-31:** Enter now types into the session (was `i`, removed); full screen moved from Enter to `f`.
