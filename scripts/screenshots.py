"""Render the README screenshots (docs/screenshots/*.svg) from made-up demo data.

    python scripts/screenshots.py

Runs the real console headlessly under a temporary HOME with fictional sessions,
machines and conversations, so nothing from your own setup can end up in a picture.
"""

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "screenshots"
SIZE = (132, 34)

home = tempfile.mkdtemp(prefix="derot-shots-")
os.environ["HOME"] = home
os.environ["DEROT_CONFIG"] = os.path.join(home, "config.yaml")
sys.path.insert(0, str(ROOT))

from derot import config, forms, sessions  # noqa: E402
from derot.sessions import Screen, Status  # noqa: E402
from derot.tui import Derot  # noqa: E402

CONFIG = """
hosts:
  gpu-box: {ssh: me@gpu-box}
accounts:
  personal: {config_dir: ~/.claude}
  work: {config_dir: ~/.claude-work}
  openai: {agent: codex, config_dir: ~/.codex}
sessions:
  - {name: api-server, dir: ~/code/api-server, account: work, note: payments API}
  - {name: web-app, dir: ~/code/web-app, account: work}
  - {name: trainer, host: gpu-box, dir: ~/projects/trainer, account: personal}
  - {name: blog, dir: ~/code/blog, account: personal}
  - {name: infra, host: gpu-box, dir: ~/infra, account: work}
  - {name: mobile-app, dir: ~/code/mobile-app, account: openai}
"""

# ANSI helpers for the fake Claude Code screens
DIM, BOLD, RESET = "\x1b[2m", "\x1b[1m", "\x1b[0m"
ORANGE, BLUE, GREY, GREEN = "\x1b[38;5;174m", "\x1b[38;5;153m", "\x1b[38;5;246m", "\x1b[38;5;114m"
RULE = f"{GREY}{'─' * 96}{RESET}"


def header(folder):
    return [f"{ORANGE} ▐▛███▜▌ {RESET}  {BOLD}Claude Code{RESET}",
            f"{ORANGE}▝▜█████▛▘{RESET}  {GREY}{folder}{RESET}", ""]


SCREENS = {
    "api-server": header("~/code/api-server") + [
        f"{GREY}❯{RESET} run the test suite and fix anything that fails", "",
        f"{GREEN}●{RESET} I'll run the tests first.", "",
        RULE,
        f" {BOLD}{BLUE}Bash command{RESET}", "",
        "   npm test -- --coverage", f"   {GREY}Run the test suite with coverage{RESET}", "",
        " Do you want to proceed?",
        f" {BLUE}❯ 1. Yes{RESET}",
        "   2. Yes, and don't ask again for npm test commands in this project",
        "   3. No, and tell Claude what to do differently (esc)",
    ],
    "trainer": header("~/projects/trainer") + [
        f"{GREY}❯{RESET} tune the learning rate schedule, keep the eval loss under 1.9", "",
        f"{GREEN}●{RESET} Trying a cosine schedule with warmup first.", "",
        f"{GREEN}●{RESET} {BOLD}Bash{RESET}(python train.py --lr 3e-4 --schedule cosine --warmup 500)",
        f"  {GREY}⎿  epoch 3/10  loss 2.041  eval 1.982{RESET}",
        f"     {GREY}epoch 4/10  loss 1.957  eval 1.931{RESET}", "",
        f"{ORANGE}✻{RESET} Training… {GREY}(2m 14s · esc to interrupt){RESET}",
    ],
    "web-app": header("~/code/web-app") + [
        f"{GREY}❯{RESET} add a dark mode toggle to the settings page", "",
        f"{GREEN}●{RESET} Added a dark mode toggle to Settings. It follows the system theme by",
        "  default and remembers the choice in localStorage.", "",
        f"  {BOLD}Changed{RESET}",
        "  - src/settings/Appearance.tsx: the toggle",
        "  - src/theme.ts: light and dark tokens",
        "  - src/theme.test.ts: 6 new tests, all passing", "",
        RULE, f"{GREY}❯{RESET} ", RULE,
    ],
    "blog": header("~/code/blog") + ["", RULE, f'{GREY}❯ Try "write a test for utils.ts"{RESET}', RULE],
}

CODEX_SCREEN = [
    f"{BOLD}>_ OpenAI Codex{RESET} {GREY}(v0.164.0){RESET}",
    f"   {GREY}~/code/mobile-app{RESET}", "",
    f"{GREY}›{RESET} add offline caching to the feed screen", "",
    f"{GREY}•{RESET} I'll cache the last page of the feed and serve it when offline.", "",
    f"{GREY}•{RESET} {BOLD}Ran{RESET} {BLUE}rg{RESET} -n \"fetchFeed\" src",
    f"  {GREY}└ src/feed/api.ts:12   export async function fetchFeed(page) {{{RESET}",
    f"     {GREY}src/feed/Feed.tsx:31 const items = await fetchFeed(1){RESET}", "",
    f"{GREY}•{RESET} {BOLD}Edited{RESET} src/feed/cache.ts {GREEN}(+42){RESET}",
    f"{GREY}•{RESET} {BOLD}Running{RESET} {BLUE}npm{RESET} test -- feed", "",
    f"{BLUE}•{RESET} Working {GREY}(41s • esc to interrupt){RESET}", "",
    f"{GREY}›{RESET} {GREY}Ask Codex to do anything{RESET}",
]

TYPING = header("~/code/web-app") + [
    f"{GREEN}●{RESET} Added a dark mode toggle to Settings.", "",
    RULE, f"{GREY}❯{RESET} /mo", RULE,
    f"  {BLUE}/model{RESET}      Set the AI model for Claude Code",
    f"  {GREY}/mobile{RESET}     {GREY}Show a QR code to download the Claude mobile app{RESET}",
]


def statuses(cfg, now):
    spec = {
        "api-server": ("waiting", "wants to use Bash: npm test -- --coverage", 40),
        "web-app": ("done", "Added a dark mode toggle to Settings. It follows the system theme.", 300),
        "trainer": ("busy", "using Bash", 15),
        "blog": ("idle", "", 3600),
        "infra": ("stopped", "", 86400 * 2),
        "mobile-app": ("busy", "using shell", 25),
    }
    out = []
    for s in cfg.sessions:
        state, message, ago = spec[s.name]
        st = Status(s, cfg.host_of(s), cfg.account_of(s), state=state, message=message,
                    ts=now - ago, transcript="/x" if state != "idle" else "")
        if s.name == "trainer":
            st.prompt = "tune the learning rate schedule, keep the eval loss under 1.9"
        if s.name == "mobile-app":
            st.prompt = "add offline caching to the feed screen"
        out.append(st)
    out.sort(key=sessions.sort_key)
    return out


def patch(typing=False):
    sessions.screen = lambda cfg, name: Screen(
        "\n".join(TYPING if typing and name == "web-app" else
                  CODEX_SCREEN if name == "mobile-app" else SCREENS.get(name, [])),
        cursor=(6, 6) if typing else None)
    sessions.fit = lambda *a: False
    now = time.time()
    sessions.conversations = lambda cfg, name, limit=40: [
        sessions.Conversation("a1", now - 3600 * 3, "Payments retry logic",
                              "add retries with backoff to the payment client",
                              "make the max delay configurable"),
        sessions.Conversation("b2", now - 86400, "Flaky webhook test",
                              "the webhook test fails about 1 in 10 runs, find out why",
                              "great, open a PR"),
        sessions.Conversation("c3", now - 86400 * 4, "",
                              "upgrade the database driver and fix the deprecations", ""),
    ]
    forms.ssh_targets = lambda home=None: [
        ("gpu-box", "me@10.0.0.12"), ("gpu-box-2", "me@10.0.0.13"),
        ("staging", "deploy@staging.example.com"), ("github.com", "known host")]
    folders = {"~/projects": ["trainer", "tokenizer", "tracking-dashboard", "notes"],
               "~": ["projects", "code", "data"]}

    async def dirs(self, parent):
        return folders.get(parent, [])
    forms.PathSuggester.dirs = dirs


async def shoot(name, setup, typing=False):
    patch(typing)
    cfg = config.load()
    app = Derot(cfg, poll_on_mount=False)
    app.action_refresh = lambda: None
    async with app.run_test(size=SIZE) as pilot:
        app.apply_poll(statuses(cfg, time.time()), {})
        await pilot.pause(0.3)
        await setup(app, pilot)
        if len(app.screen_stack) == 1:
            app._preview_key = None
            app.refresh_preview()
        await pilot.pause(0.8)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{name}.svg").write_text(app.export_screenshot(title="derot"))
        print("wrote", OUT / f"{name}.svg")


async def overview(app, pilot):
    pass  # the session that needs you is on top and selected


async def typing(app, pilot):
    app.query_one("DataTable").move_cursor(row=1)  # web-app
    await pilot.pause(0.3)
    app.action_live()


async def working(app, pilot):
    app.query_one("DataTable").move_cursor(row=2)  # trainer
    await pilot.pause(0.3)


async def codex(app, pilot):
    table = app.query_one("DataTable")
    table.move_cursor(row=table.get_row_index("mobile-app"))
    await pilot.pause(0.3)


async def new_session(app, pilot):
    await pilot.press("n")
    await pilot.pause(0.3)
    app.screen.query_one("#host").value = "gpu-box"
    await pilot.pause(0.2)
    await pilot.press(*"~/projects/tr")


async def resume(app, pilot):
    from derot.forms import ResumePicker
    app.push_screen(ResumePicker(app.cfg, "api-server", "a1"))


async def add_machine(app, pilot):
    from derot.forms import HostForm
    app.push_screen(HostForm(app.cfg))
    await pilot.pause(0.3)
    await pilot.press(*"gpu")


async def main():
    Path(os.environ["DEROT_CONFIG"]).write_text(CONFIG)
    await shoot("overview", overview)
    await shoot("working", working)
    await shoot("typing", typing, typing=True)
    await shoot("codex", codex)
    await shoot("new-session", new_session)
    await shoot("resume", resume)
    await shoot("add-machine", add_machine)


if __name__ == "__main__":
    asyncio.run(main())
