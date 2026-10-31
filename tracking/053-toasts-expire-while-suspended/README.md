# Toasts raised while attached or logging in may expire unseen

| Field | Value |
|---|---|
| Status | open |
| Type | ux |
| Priority | P3 |
| Size | S |
| Verified | suspected |
| Source | bug hunt after 045, 2026-10-31 |

## Problem

During `App.suspend()` (attach, login, editor, setup), worker results still arrive through `call_from_thread(self.notify, …)`, for example "hook setup on X failed (press u)". Toast timers keep running while suspended, so after a long attach the message may already be gone. Errors and warnings are still logged (`Derot.notify`), so they aren't lost entirely.

## Where

`derot/tui.py` `notify()` (line 180), `attach()`, `login()`

## Fix (proposed)

Queue warning and error toasts while suspended and show them on resume.

## Done when

- [ ] Reproduced in a real terminal, then fixed or closed.
