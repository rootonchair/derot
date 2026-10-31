# ccdeck

[![tests](https://github.com/rootonchair/ccdeck/actions/workflows/tests.yml/badge.svg)](https://github.com/rootonchair/ccdeck/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

One terminal console for every Claude Code session you run: across **projects**, **Claude
accounts** and **machines** (this computer plus any machine you can SSH into), in one list.
See which sessions need you, watch Claude work, and type into any of them without leaving
the console.

![ccdeck: a session needs approval, its live screen on the right](docs/screenshots/overview.svg)

## Features

**Every session at a glance.** Sessions that need you (a permission prompt or a question
with options) sort to the top, then finished ones, then the ones still working. The summary
bar counts them, and you get a desktop notification when a session needs you.

**Watch Claude work.** The right-hand panel shows the selected session's details and its
live screen, exactly as Claude Code draws it, for local and SSH sessions alike.

![a session working on a remote GPU machine](docs/screenshots/working.svg)

**Type into any session from the console.** Press Enter or click the right panel and every
key goes straight to Claude: slash commands, `/model`, menus, autocomplete, Esc, paste. Press
`1`–`9` on the list to answer a prompt in one keystroke, or `f` for Claude's own full-screen
UI. `Ctrl-q` always brings you back.

![typing into a session: Claude's slash-command menu in the preview](docs/screenshots/typing.svg)

**Pick up old conversations.** `R` lists a session's past conversations with their titles,
age and last prompt, and resumes the one you pick. `c` continues the session's own last
conversation.

![the resume picker](docs/screenshots/resume.svg)

**No YAML required.** Add sessions, machines and accounts from forms. The project folder
field lists matching folders as you type, on the chosen machine (over SSH for remote ones),
and the SSH target field lists hosts from your `~/.ssh/config` and `known_hosts`.

![new session form with folder suggestions from an SSH machine](docs/screenshots/new-session.svg)

![add machine form with SSH targets](docs/screenshots/add-machine.svg)

**Sessions outlive the console.** Every session runs in tmux, so it keeps going when you
quit ccdeck, close the laptop lid or lose the SSH connection.

## How it works

- **tmux**: each session is a tmux session `cc-<name>` on a private tmux server
  (`tmux -L ccdeck`), so it survives detaching and never touches your own tmux setup.
- **SSH**: remote hosts are reached with plain `ssh` (shared ControlMaster connection, one
  call per host per refresh). Nothing runs on the VM besides tmux, python3 and Claude Code.
- **Hooks**: `ccdeck setup` installs a tiny stdlib-only script, `~/.ccdeck/hook.py`, and
  registers it as a Claude Code hook. It writes `~/.ccdeck/state/<name>.json` on each event
  (prompt submitted, tool use, permission prompt, stop), so status is accurate without screen
  scraping.
- **Accounts**: each account is a Claude Code config folder passed via `CLAUDE_CONFIG_DIR`,
  each with its own login and settings.

## Install

Requirements: Python 3.9+, [tmux](https://github.com/tmux/tmux) and
[Claude Code](https://docs.anthropic.com/en/docs/claude-code) on every machine you use.
Developed and used on macOS; the Linux code paths (tmux, `notify-send` notifications) are
covered by CI but haven't seen much real use yet.

```sh
pipx install git+https://github.com/rootonchair/ccdeck     # or: uv tool install git+https://github.com/rootonchair/ccdeck
```

On macOS, `brew install tmux pipx` first. Each SSH machine needs `tmux`, `python3`, Claude
Code, and key-based SSH access (`ssh my-vm true` works without a password prompt).

## Setup

1. Run `ccdeck`. On first run it creates `~/.config/ccdeck/config.yaml` (override with
   `CCDECK_CONFIG`) and opens the console.
2. Press `n` to add a session: pick a machine, a project folder (matching folders are listed
   as you type) and a Claude account. Choose **+ add a machine (SSH)…** or **+ add an account…** in the dropdowns
   to create those on the spot. Saving installs the status hooks for any new machine/account
   automatically, and offers to log in to a new account right away.
3. Press `Enter` on a session to start it and type into it from the right panel; `Ctrl-q`
   stops typing. `f` opens Claude's own full-screen UI instead.

No YAML editing needed. `e` edits the selected session, `d` removes it, `l` opens Claude Code
for the session's account so you can `/login`. The config file is still plain YAML if you
prefer it (`E` opens it in `$EDITOR`); saving from the console rewrites it without comments
and keeps your original as `config.yaml.bak`.

A VM needs tmux, python3, Claude Code, and key-based SSH (`ssh my-vm true` works without a
password prompt). From the command line, the same setup is `ccdeck login ACCOUNT [--host H]`
and `ccdeck setup`.

<details><summary>Config file reference</summary>

```yaml
hosts:
  vm:
    ssh: user@my-vm            # anything `ssh` accepts, incl. ~/.ssh/config aliases
    claude: claude             # optional: command/full path for Claude Code there
accounts:
  personal: {config_dir: ~/.claude}
  work:
    config_dir: ~/.claude-work
    env: {ANTHROPIC_API_KEY: sk-ant-...}   # optional
sessions:
  - {name: shop-api, host: local, dir: ~/code/shop-api, account: work, note: payments refactor}
  - {name: infra,    host: vm,    dir: ~/infra,         account: work, args: "--model opus"}
notify: {on_waiting: true, on_done: true, sound: Glass}
refresh: 3
detach_key: C-q
```

</details>

## Keys

The console has the session list on the left. On the right are the selected session's
details and a **preview**. The preview shows the session's live screen, exactly as Claude draws
it (the same view you get when typing live or attaching); stopped sessions show their last
conversation instead. Press Enter (or click the right panel) to type straight into the
session from the preview (slash commands, `/model` and menus all work), or `1`–`9` to pick a
prompt option. Go full screen (`f`) only for longer work.

| Key | Action |
|---|---|
| `Enter` / click the right panel | Type into the selected session: every key (letters, `/`, arrows, Tab, Esc, Ctrl-C, paste) goes straight to Claude, and the preview shows Claude's own UI updating as you type, including slash-command menus, `/model`, autocomplete and pickers. Starts the session first if it's stopped. `Ctrl-q` stops typing. A click on a row only selects it |
| `f` | Full screen: Claude's own UI in this terminal (attach; starts it first if stopped). `Ctrl-q` comes back |
| `1`–`9` | When a session needs you: pick that numbered option in its prompt |
| `p` | Preview: switch between auto (screen while running, conversation once stopped), conversation (from Claude's transcript) and screen |
| `s` | Start fresh in the background and stay in ccdeck (watch it in the preview, Enter to type) |
| `c` | Continue this session's last conversation (falls back to the folder's newest, `claude --continue`), in the background like `s` |
| `R` | Resume: pick any past conversation of the session's folder and account (title, age, last prompt), then start it with `claude --resume` |
| `x` `x` | Stop (press twice within 3 s) |
| `n` | New session (form) |
| `e` | Edit the selected session (form) |
| `d` | Remove the selected session from ccdeck |
| `l` | Log in to the selected session's account (`/login`) |
| `E` | Open the config file in `$VISUAL`/`$EDITOR`, reload on exit |
| `u` | Run setup (install hooks) |
| `r` | Refresh now |
| `q` | Quit (sessions keep running) |

Inside a session, `Ctrl-q` (configurable with `detach_key`) returns to ccdeck. `Ctrl-b d`
always works too. Coming back from a finished session marks it as seen (done → idle).

## Command line

```
ccdeck                      open the console (creates the config on first run)
ccdeck init                 create the config file
ccdeck setup [--remove]     install / remove status hooks on every host+account
ccdeck ls                   print a status table
ccdeck start NAME [-c] [-r ID] [-d]   start (-c continue last conversation, -r resume that
                                      conversation, -d don't attach)
ccdeck history NAME [-n N]            list past conversations (ids for -r)
ccdeck attach NAME          attach, then mark seen
ccdeck stop NAME
ccdeck watch                poll + notifications only, for when the console is closed
ccdeck login ACCOUNT [--host H]
ccdeck log [-f] [-n N]       show the log, for tracing errors
```

`ccdeck watch` gives you desktop alerts without keeping the console open, e.g. in a spare
terminal tab or a login item.

## Troubleshooting

Start with the log: **`ccdeck log`** shows the last lines of `~/.ccdeck/ccdeck.log`
(`ccdeck log -f` follows it live). It records every action, every failure with the full error
output, and tracebacks for anything unexpected. Error toasts in the console are logged too, so
a message that disappeared can still be read there. For even more detail, run with
`CCDECK_DEBUG=1 ccdeck` to log every command ccdeck runs (API keys are masked). Errors inside
the status hook itself go to `~/.ccdeck/hook-errors.log` on that machine.

- **`claude` not found**: sessions run in your login shell, but if it still isn't found set
  `claude:` to the full path for that host (`which claude` on that machine).
- **Session shows "needs you: Claude hasn't started yet"**: Claude is on a screen that comes
  before the session, such as "trust this folder?" or a new account's login. Press Enter (or
  click the right panel) and answer it. If nothing is there, press `u` to reinstall the hooks.
- **Session stuck on idle**: status hooks are missing for that account/host. Starting a
  session sets them up; otherwise press `u` (or run `ccdeck setup`).
- **Two accounts log each other out on the Mac**: Claude Code stores logins in the macOS
  keychain, so two subscription logins can clash. Give one account an API key via its `env`
  (`ANTHROPIC_API_KEY: ...`).
- **Detach key conflicts** with an app you use inside sessions: change `detach_key` (e.g.
  `C-]`). `Ctrl-b d` always works.
- **Sessions started outside ccdeck don't appear**: ccdeck only tracks sessions it starts.
  Add them with `n`, exit the old `claude`, then press `c` to continue the same conversation.

## Known issues

See [tracking/](tracking/README.md) for everything open. The main ones:

- Quitting waits silently for background work to finish (up to a minute while hooks are
  being set up).
- After the console quits, a session stays at the preview's size if you attach with plain
  tmux instead of ccdeck.
- An SSH machine whose login shell is csh/tcsh isn't supported yet.
- Claude Code features that need a hook ccdeck doesn't use (for example compaction) are
  handled from Claude Code's documentation and haven't been seen live.

## Development

```sh
uv venv && uv pip install -e '.[test]'
.venv/bin/pytest          # needs tmux; uses a fake `claude` and fake `ssh`, no VM needed
.venv/bin/pyflakes ccdeck tests scripts
.venv/bin/python scripts/screenshots.py   # regenerate docs/screenshots from demo data
```

## License

[MIT](LICENSE).

ccdeck is an independent project. It is not affiliated with, endorsed by or sponsored by
Anthropic. Claude and Claude Code are trademarks of Anthropic.
