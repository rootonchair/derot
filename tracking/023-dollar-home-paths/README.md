# `$HOME/...` in `config_dir`/`dir` reached Claude as a literal relative path

| Field | Value |
|---|---|
| Status | done |
| Type | bug |
| Priority | P1 |
| Size | S |
| Verified | confirmed (bug-hunt repro) |
| Source | bug-hunt agent, 2026-10-30 |

## Problem

`qpath()` single-quotes anything that isn't `~`, so `config_dir: "$HOME/.claude"` exported the literal string `CLAUDE_CONFIG_DIR=$HOME/.claude` (relative), and the installer created a `$HOME` folder. 008's fix was incomplete.

## Fix

`config.norm_path()` turns `$HOME/x` and `${HOME}/x` into `~/x` when the config is parsed (dirs and config dirs), so everything downstream sees `~`. Test: `test_023_dollar_home_paths_work`.
