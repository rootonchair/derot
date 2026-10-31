# Semicolons typed live or pasted are dropped

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P0 |
| Size | S |
| Verified | confirmed (repro: `ls;` `;` `a\;` arrive as `lsa;`) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

tmux treats any command-line argument that *ends* in `;` as a command separator (and `\;` as an escaped `;`). `send_input()` passes typed text as one argv element, so a batch ending in `;` loses it; a `;` typed on its own (one key per batch, the normal case on a fast host) is never sent at all, and `\;` arrives as `;`. `paste()` has the same problem through `set-buffer -- <text>`: pasting `echo hi;` sends `echo hi`. Shell commands, code and prose all get silently changed.

## Where

- `derot/sessions.py:549` `send_input()` (`send-keys -l -- value`)
- `derot/sessions.py:531` `paste()` (`set-buffer -- text`)

## Proposed fix

Escape the last character for tmux: when a literal argument ends in `;`, send `value[:-1] + "\\;"` (tmux turns a trailing `\;` back into `;`, and this also keeps a user's `\;` intact). Alternatively send text with `send-keys -H` (hex bytes) and load paste text with `load-buffer -` from stdin.

## Done when

- [x] `test_029_typed_semicolons_reach_the_session` and `test_029_pasted_semicolon_reaches_the_session` pass (remove xfail).

## Notes

Repro: `tests/test_bughunt_new.py::test_029_typed_semicolons_reach_the_session` (xfail strict).

## Review (2026-10-31)

**Verdict:** confirmed. Both tests fail with `--runxfail` (`lsa;` and `echo hi`), and the tests test exactly the stated bug. **Priority:** P1 → P0.

- When typing live at normal speed, every key is its own batch, so **every `;` typed on its own is dropped**, silently, on the main input path (code, shell, prose). That is the most common input path in the app.
- **The proposed fix is wrong for backslashes** (checked on tmux 3.8, isolated socket): `value[:-1] + "\\;"` turns the user's `a\;` into the argument `a\\;`, and tmux delivers `a;`. tmux un-escapes the whole argument once it takes the `\;` path, so the test's `a\;` case would still fail. `send-keys -H` would need tmux ≥ 3.0, but 024 supports older tmux.
- **Fix that works (checked):** split off the trailing semicolons. Send the rest as one `-l` literal (it no longer ends in `;`, so its backslashes stay as typed), then send each `;` as a separate `-l -- '\;'` argument, which tmux has always turned into `;`. Result: `a\` + `\;` + `\;` → `a\;;`. For paste, use `set-buffer -- <rest>` and then `set-buffer -a -- '\;'` for each one (checked: `x\;` + `\;` → `x;;`). Put this in one helper used by both `send_input` and `paste`.
- **Merge or fix together with 031:** move paste into `send_input` as a `("paste", text)` chunk that emits `set-buffer`/`paste-buffer` in the same argv. That gives one escaping helper, one tmux call and the correct order.

## Fix (2026-10-31)

Trailing semicolons go as separate `\;` arguments (`sessions._literal`), for typed text and pastes (`set-buffer -a`). Verified on tmux 3.8. Tests: `test_029_*`.
