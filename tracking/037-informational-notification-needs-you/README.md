# Informational notifications are shown as "needs you"

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P2 |
| Size | S |
| Verified | suspected (apply() behaviour confirmed by test) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

Every `Notification` that isn't an idle nudge sets `waiting` and triggers a "needs you" alert, including informational types such as `auth_success` (after `/login`).

## Where

- `ccdeck/hook.py:154` `apply()` Notification branch

## Proposed fix

Set `waiting` only for `permission_prompt` / `elicitation_dialog` (and for payloads with no `notification_type`, for older Claude Code); ignore other known informational types.

## Done when

- [x] `test_037_informational_notification_is_not_needs_you` passes.

## Notes

Repro: `tests/test_bughunt_new.py::test_037_informational_notification_is_not_needs_you` (xfail strict).

## Review (2026-10-31)

**Verdict:** confirmed (the docs back it up). **Priority:** P3 → P2.

- The docs now list 13 `notification_type` values: `permission_prompt`, `idle_prompt`, `auth_success`, `elicitation_dialog`, `elicitation_url_dialog`, `elicitation_complete`, `elicitation_response`, `agent_needs_input`, `agent_completed`, `quota_auto_resume_fired|stale|disabled`, `plugin_notification`. Everything except `idle_prompt` turns into "needs you", pins the row to the top and sends an alert. `auth_success` is rare (the `l` login pane has no `CCDECK_SESSION`), but `agent_completed`, `elicitation_complete` and `plugin_notification` can fire during normal work, hence P2.
- **The proposed allowlist is incomplete:** also treat `elicitation_url_dialog` and `agent_needs_input` as needs-you. Recommended rule: needs-you if the type is in {permission_prompt, elicitation_dialog, elicitation_url_dialog, agent_needs_input}, *or* there is no type (older Claude Code). Any other type leaves the state unchanged. Unknown future types then default to "not needs you", which is the safer failure for alerts. Optionally show `quota_auto_resume_*` as the row message.
- Fix together with 036 (both are `apply()` classification).

## Fix (2026-10-31)

Only permission_prompt, elicitation_dialog, elicitation_url_dialog, agent_needs_input (or no type) mean needs-you; other types are ignored. Test: `test_037_*`.
