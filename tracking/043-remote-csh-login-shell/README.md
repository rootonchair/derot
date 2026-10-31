# Every ssh call fails when a VM account's login shell is csh/tcsh

| Field | Value |
|---|---|
| Status | open |
| Type | bug |
| Priority | P3 |
| Size | M |
| Verified | confirmed (review) |
| Source | bug review, 2026-10-31 |

## Problem

`remote.wrap()` sends `shlex.join(argv)` to ssh, parsed by the remote passwd shell; csh/tcsh reject multi-line single-quoted strings and `!` triggers history expansion, so poll/start/setup fail and the host shows offline. fish mostly works.

## Where

`derot/remote.py` `wrap()`, `sh()`, `python()`

## Proposed fix

Send scripts over stdin (`sh -s`) or base64-encode them, so the remote login shell only sees a fixed simple command.

## Done when

- [ ] Polling, start and setup work against a VM whose login shell is tcsh.

## Notes

Found in the 2026-10-31 review of 032.
