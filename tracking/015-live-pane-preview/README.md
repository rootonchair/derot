# Live preview of the selected session's screen

| Field | Value |
|---|---|
| Status | done |
| Type | feature |
| Priority | P1 |
| Size | S–M |
| Verified | n/a |
| Source | derot review, 2026-10-29 |

## Problem

You can't see what Claude is asking without attaching.

## Where

- `derot/tui.py` detail panel

## Proposed fix

For the selected row only, on its own timer: `tmux capture-pane -p -J -S -40 -t '=cc-x:'`; show the last lines in the detail panel (toggle with `p`).

## Done when

- [x] run_test: selected running session shows pane text; switching rows updates it.

## Notes

**2026-10-30:** Layout modelled on ai-devkit's `agent console`: list on the left; header, preview and reply box on the right. The preview reads Claude's transcript (`sessions.conversation`, path stored by the hook) and skips sidechain/meta/injected entries. When a session needs you, or has no transcript yet, it shows the live screen (`capture-pane`). `p` cycles auto/conversation/screen. Only the selected session is fetched, every 2 s. Below 110 columns the panes stack vertically.

**2026-10-30 (follow-up, from real use):**
- A missing transcript (Claude creates it only with the first message) showed as an error. Now it means "nothing yet", and auto mode shows the screen.
- The screen view lost all styling (`capture-pane -p` is plain text), so Claude's dim suggestions, colours and highlighted options were invisible. It now captures with `-e` and renders the ANSI.
- The detached session's window was 213 columns wide, so its UI was cut off in the preview. `sessions.fit()` now resizes a session nobody is attached to so it matches the preview (Claude re-lays out as on a terminal resize). `attach()` unsets the window's `window-size` first, so the attaching terminal takes over again. Attached sessions are never resized.
- The header repeated Claude's whole last reply; it's now one short line.
- Desktop and toast notifications are a first-sentence brief, at most 90 characters (`notify.brief`). The `(account@host)` suffix from the spec was dropped.

**2026-10-31, live typing (`t`):** The reply box sends a whole line at once, so Claude's own UI never reacted while you typed: no slash menu, no `/model` picker, no suggestions. Live mode forwards each key to the session (`send-keys`, literal text batched in order on one worker; paste goes through `paste-buffer -p` for bracketed paste) and refreshes the screen every 0.3 s with tmux's cursor drawn. App keys (`q`, `x`, `d`, ...) and Enter are typed, not run. `Ctrl-q` (overriding Textual's quit only while live) or clicking away stops it. Verified on a real Claude Code 2.1.312 session: typing `/mod` showed its slash menu with `/model` highlighted. Note: the stop key is always `Ctrl-q`, even if `detach_key` is set to something else. Tests: `test_live_typing_reaches_claude_key_by_key`, `test_tmux_key_mapping`, `test_render_screen_draws_cursor`.

