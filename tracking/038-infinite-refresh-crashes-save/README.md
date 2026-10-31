# `refresh: .inf` is accepted, then every save crashes

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | confirmed (repro test: `OverflowError` in `to_dict`) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

`parse()` accepts any float `>= 1`, including infinity. `to_dict()` then calls `int(cfg.refresh)`, which raises `OverflowError`. The console's `save_config()` only catches `ConfigError`/`OSError`, so saving any form crashes the console. NaN is silently turned into 1.

## Where

- `derot/config.py:224` refresh parsing
- `derot/config.py:271` `to_dict()`
- `derot/tui.py:764` `save_config()`

## Proposed fix

Reject non-finite values in `parse()` (`math.isfinite`) with a `ConfigError`, and optionally cap the value.

## Done when

- [x] `test_038_infinite_refresh_is_rejected_or_saves` passes.

## Notes

Repro: `tests/test_bughunt_new.py::test_038_infinite_refresh_is_rejected_or_saves` (xfail strict).

## Review (2026-10-31)

**Verdict:** confirmed. The test fails with `--runxfail` (`OverflowError` at `config.py:271`). **Priority:** P3 (unchanged). Someone has to type `.inf` by hand.

- **Fix:** sound. `math.isfinite()` → `ConfigError`. Consider an upper limit (for example 3600), because a huge finite value is accepted and leaves the console looking frozen. NaN already falls back to 1 because `max(1.0, nan)` returns 1.0, which is harmless.

## Fix (2026-10-31)

refresh must be in (0, 3600] (rejects .inf/.nan), then clamped to ≥1. Test: `test_038_*`.
