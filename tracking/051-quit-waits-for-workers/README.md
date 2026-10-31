# Quitting the console silently waits for background workers

| Field | Value |
|---|---|
| Status | open |
| Type | ux/bug |
| Priority | P3 |
| Size | S–M |
| Verified | confirmed (repro) |
| Source | bug hunt after 045, 2026-10-31 |

## Problem

Textual thread workers run in asyncio's default executor, which `asyncio.run` joins on exit. After `q`, the terminal is restored but the process doesn't return until running workers finish. A hook setup can take up to about a minute (40 s check plus merges). This looks like a hang, and Ctrl-C then interrupts the setup. Any result the worker reports afterwards is lost: `call_from_thread` raises `RuntimeError: App is not running`. A minimal Textual app with a 3 s worker returns from `run()` only after 3 s.

## Where

`derot/tui.py` `install_hooks_worker()` (line 879) and the other `@work(thread=True)` workers

## Fix (proposed)

On quit, if a hooks worker is running, print "finishing hook setup on X…" or ask first. Wrap `call_from_thread` in workers so a closed app is ignored. Since 045, 046 and 047, an interrupted setup is repaired at the next start, so this is mostly UX.

## Done when

- [ ] Quitting during a setup says what it's waiting for, or doesn't wait.
