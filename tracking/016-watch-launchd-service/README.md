# `watch` as a background service (launchd), no duplicate alerts

| Field | Value |
|---|---|
| Status | open |
| Type | feature |
| Priority | P1 |
| Size | S |
| Verified | n/a |
| Source | ccdeck review, 2026-10-29 |

## Problem

Alerts only arrive while the console or a `watch` terminal is open.

## Where

- `ccdeck/cli.py` `cmd_watch()`

## Proposed fix

`ccdeck service install|uninstall|status` writes `~/Library/LaunchAgents/com.ccdeck.watch.plist` (KeepAlive, logs to `~/.ccdeck/`). Uses the lock from 007 so the TUI doesn't double-notify.

## Done when

- [ ] plist generated correctly (unit test); manual `launchctl` check.

## Notes

_Add findings, decisions and links to commits here._
