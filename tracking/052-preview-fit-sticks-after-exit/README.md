# Preview resizing leaves sessions at the preview's size after the console quits

| Field | Value |
|---|---|
| Status | open |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | confirmed (repro with tmux) |
| Source | bug hunt after 045, 2026-10-31 |

## Problem

`fit()` uses `resize-window`, which sets the window's `window-size` to `manual`. Only `sessions.attach()` (derot attach / enter) undoes it. After the console quits, a plain `tmux -L derot attach -t cc-x` shows the window at the last preview size (for example 60x15), and it stays that way.

## Where

`derot/sessions.py` `fit()` (line 683), `derot/tui.py` `preview_worker()`

## Fix (proposed)

On console exit, unset `window-size` for every session the console fitted. Or fit with `-A`/`aggressive-resize` instead of manual sizing.

## Done when

- [ ] After quitting the console, a direct tmux attach follows the terminal size.
