# `setup` replaces a symlinked settings.json with a plain file

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P3 |
| Size | S |
| Verified | confirmed (repro test) |
| Source | bug-hunt agent, 2026-10-31 |

## Problem

The merge script writes a temp file in the config folder and `os.replace()`s it over `settings.json`. When `settings.json` is a symlink (dotfiles repos, stow, chezmoi), the link is replaced by a regular file, so the user's dotfile no longer gets the hooks and later dotfile edits stop applying. The new file is also `0600` (mkstemp) instead of the original mode.

## Where

- `derot/installer.py:58` and `:121` `MERGE_SCRIPT` (path / mkstemp / `os.replace`)

## Proposed fix

Resolve `path = os.path.realpath(path)` before reading/writing, create the temp file in that directory, and copy the original file's mode onto it before `os.replace`.

## Done when

- [x] `test_033_setup_keeps_symlinked_settings` passes.

## Notes

Repro: `tests/test_bughunt_new.py::test_033_setup_keeps_symlinked_settings` (xfail strict).

## Review (2026-10-31)

**Verdict:** confirmed. The test fails with `--runxfail` ("symlink replaced by a regular file") and also checks the 0644 mode. **Priority:** P2 → P3. It only affects users who manage `settings.json` with stow, chezmoi or a dotfiles repo, and `.derot-bak` keeps the original contents.

- **Fix:** sound (`realpath`, a temp file in the real file's folder, `copymode`). Keeping the mode also helps when the file isn't a symlink, since mkstemp makes every rewritten file 0600.
- **Side effect to note:** following the link writes `python3 ~/.derot/hook.py …` into the user's *tracked* dotfile. On other machines that sync the dotfiles but don't have derot, every Claude event runs a hook that fails, with a non-zero exit and a hook error shown in verbose mode. The fix should print a note when the target is a symlink ("hooks written to <real path>"), and `setup --remove` has to follow the link as well.

## Fix (2026-10-31)

The merge writes through the symlink (`realpath`) and keeps the file mode. Test: `test_033_*`.
