# Attach fails completely on tmux < 2.9 (no `window-size`)

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P1 |
| Size | S |
| Verified | suspected (bug hunt; can't test old tmux here). The `;`-chain abort was confirmed. |
| Source | bug-hunt agent, 2026-10-30 |

## Problem

attach chained `set-option -w -u window-size ; attach`. On old tmux the first command fails and tmux stops the chain, so attach never runs.

## Fix

The window-size reset is now a separate, best-effort command before attach. Test: `test_024_attach_does_not_chain_on_window_size`.
