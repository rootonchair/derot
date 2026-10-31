# Ctrl-P while typing live opens the command palette

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | confirmed (repro test) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

Textual adds `ctrl+p` → command palette as a *priority* binding, which runs before `LiveView.on_key`. While typing live, Ctrl-P (previous history line in Claude Code) never reaches the session; the palette opens and steals focus, which also ends live mode via `on_blur`.

## Where

- `ccdeck/tui.py:116` `CCDeck` (inherits `ENABLE_COMMAND_PALETTE`)
- `ccdeck/tui.py:578` `check_action()`

## Proposed fix

Set `ENABLE_COMMAND_PALETTE = False`, or return False from `check_action()` for `command_palette` while `self.live`.

## Done when

- [x] `test_034_ctrl_p_reaches_the_session_while_typing_live` passes.

## Notes

Repro: `tests/test_bughunt_new.py::test_034_ctrl_p_reaches_the_session_while_typing_live` (xfail strict).

## Review (2026-10-31)

**Verdict:** confirmed. The test fails with `--runxfail`. **Priority:** P3 (unchanged).

- One correction: live mode does **not** end. Checked: after Ctrl-P, `app.live` is still `a`, but the palette is on top (`screen_stack` = 2) and every following key goes into it. The effect for the user is the same.
- **Fix:** `ENABLE_COMMAND_PALETTE = False` is the simplest; ccdeck doesn't use the palette. If it's kept, `check_action('command_palette')` returning False while live also works.
- **Missing, related (I would make a P2 item):** other keys are dropped while typing live because `tmux_key()` has no mapping for them: `shift+enter` / `alt+enter` (Claude Code's newline for multi-line prompts), `ctrl+left`/`ctrl+right` (word movement) and `ctrl+_`. Checked: none of them reach `send_input`. tmux understands `M-Enter`, `C-Left`, `S-Enter` (extended keys). `ctrl+j` and `\`+Enter do work as newline workarounds.

## Fix (2026-10-31)

`check_action` disables `command_palette` while typing live. Test: `test_034_*`.
