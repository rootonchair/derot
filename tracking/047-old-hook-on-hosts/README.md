# Hosts kept an older hook.py until `ccdeck setup` was re-run

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S |
| Verified | confirmed (test) |
| Source | bug hunt after 045, 2026-10-31 |

## Problem

hook.py was only updated by `ccdeck setup` or `u`. After an upgrade, hosts quietly kept the old status logic, so fixes such as 036, 037, 040 and 044 never took effect there.

## Where

`ccdeck/installer.py` `hooks_present()` / `ensure_hooks()`

## Fix

Same check as 046. A hook.py that differs from this version counts as missing, so it is updated before the next start of a session on that host.

## Done when

- [x] Covered by a test.

## Notes

Test: `test_bughunt_new.py::test_047_older_hook_is_replaced_before_start`. Sessions that are already running keep the old hook until they are restarted. If two ccdeck versions manage the same host, each start re-uploads its own copy, which is harmless.
