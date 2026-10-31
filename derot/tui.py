"""The derot console (Textual)."""

from __future__ import annotations

import copy
import os
import shlex
import shutil
import subprocess
import threading
import time
from typing import Dict, List, Optional

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Footer, Static

from . import config as config_mod
from . import installer, sessions
from .config import Config, ConfigError
from .forms import Confirm, ResumePicker, SessionForm, new_pairs
from .log import log
from .notify import Notifier, brief
from .sessions import STYLE, Status

STOP_CONFIRM_SECS = 3.0
ERROR_TOAST_SECS = 30
PREVIEW_SECS = 2.0
LIVE_SECS = 0.3  # screen refresh while typing live
NARROW_WIDTH = 110
PREVIEW_MODES = ("auto", "conversation", "screen")
ROLE_STYLE = {"you": ("you", "bold #5ab8f0"), "claude": ("claude", "bold #5fd68a"),
              "tool": ("→", "dim"), "note": ("·", "italic #f5b942")}


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def render_conversation(items: List[dict], agent: str = "claude") -> Text:
    """The conversation view; the agent's replies are labelled with its name."""
    if not items:
        return Text("no conversation yet", style="dim")
    t = Text()
    for i, it in enumerate(items):
        label, style = ROLE_STYLE.get(it.get("role", ""), ("?", "dim"))
        if it.get("role") == "claude":
            label = agent
        if i:
            t.append("\n" if it.get("role") == "tool" else "\n\n")
        if it.get("role") == "tool":
            t.append(f"  {label} {it.get('text', '')}", style=style)
        elif it.get("role") == "note":
            t.append(f"{label} {it.get('text', '')}", style=style)
        else:
            t.append(f"{label}\n", style=style)
            t.append(str(it.get("text", "")))
    return t


def find_editor() -> List[str]:
    for var in ("VISUAL", "EDITOR"):
        val = os.environ.get(var, "").strip()
        if val:
            return shlex.split(val)
    for name in ("nano", "vim", "vi"):
        if shutil.which(name):
            return [name]
    return ["vi"]


def render_screen(scr: "sessions.Screen", cursor: bool) -> Text:
    """ANSI screen -> Text, optionally drawing tmux's cursor (reverse video)."""
    body = Text.from_ansi(scr.text)
    if not cursor or scr.cursor is None:
        return body
    x, y = scr.cursor
    lines = body.split("\n", allow_blank=True)
    while len(lines) <= y:
        lines.append(Text(""))
    line = lines[y]
    if len(line) <= x:
        line.append(" " * (x - len(line) + 1))
    line.stylize("reverse", x, x + 1)
    return Text("\n").join(lines)


class LiveView(Static):
    """The preview while typing live: every key goes to the session (except Ctrl-q)."""

    can_focus = False  # only while live

    def on_key(self, event: events.Key) -> None:
        app = self.app
        if not getattr(app, "live", None):
            return
        event.stop()
        event.prevent_default()
        if event.character and event.is_printable:
            app.queue_input("text", event.character)
        else:
            key = sessions.tmux_key(event.key)
            if key:
                app.queue_input("key", key)

    def on_paste(self, event: events.Paste) -> None:
        if getattr(self.app, "live", None):
            event.stop()
            self.app.queue_input("paste", event.text)

    def on_blur(self, event: events.Blur) -> None:
        if getattr(self.app, "live", None):
            self.app.stop_live()


class Derot(App):
    TITLE = "derot"
    CSS = """
    Screen { layout: vertical; }
    #summary { height: 1; padding: 0 1; background: $panel; }
    #main { height: 1fr; }
    #left { width: 52; min-width: 34; border-right: solid $panel-lighten-2; }
    #table { height: 1fr; }
    #empty { height: 1fr; content-align: center middle; color: $text-muted; display: none; }
    #right { width: 1fr; }
    #detail { height: auto; max-height: 8; padding: 0 1; }
    #preview-box { height: 1fr; padding: 0 1; border-top: solid $panel-lighten-2;
                   border-title-color: $text-muted; }
    #preview.screen { text-wrap: nowrap; text-overflow: clip; }
    #preview-box.live { border-top: heavy $accent; border-title-color: $accent; }
    .narrow #main { layout: vertical; }
    .narrow #left { width: 100%; height: 40%; border-right: none;
                    border-bottom: solid $panel-lighten-2; }
    """

    BINDINGS = [
        Binding("enter", "open", "Type", priority=True),
        Binding("f", "fullscreen", "Full screen"),
        Binding("ctrl+q", "ctrl_q", "Quit", show=False, priority=True),
        Binding("p", "preview_mode", "Preview"),
        *[Binding(str(d), f"press_digit('{d}')", show=False) for d in range(1, 10)],
        Binding("s", "start", "Start"),
        Binding("c", "continue", "Continue"),
        Binding("R", "resume", "Resume…"),
        Binding("x", "stop", "Stop"),
        Binding("n", "new_session", "New"),
        Binding("e", "edit_session", "Edit"),
        Binding("d", "remove_session", "Remove"),
        Binding("l", "login", "Log in"),
        Binding("E", "edit", "Edit file", show=False),
        Binding("u", "setup", "Setup hooks"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, cfg: Config, created: bool = False, poll_on_mount: bool = True):
        super().__init__()
        self.cfg = cfg
        self.created = created
        self.poll_on_mount = poll_on_mount
        self.statuses: List[Status] = []
        self.offline: Dict[str, str] = {}
        self.updated: Optional[float] = None
        self.notifier = Notifier(cfg.notify, toast=self._toast_alert, defer_to_watch=True)
        self._poll_lock = threading.Lock()
        self._stop_armed: Optional[tuple] = None
        self._timer = None
        self._preview_lock = threading.Lock()
        self.preview_mode = "auto"
        self._preview_key: Optional[tuple] = None  # what the preview pane currently shows
        self._preview_text = ""
        self.live: Optional[str] = None  # session being typed into, if any
        self._input: List[tuple] = []  # pending (session, kind, value) live input
        self._input_lock = threading.Lock()
        self._sending = False
        self._live_timer = None

    # ------------------------------------------------------------ errors

    def notify(self, message, *, title="", severity="information", timeout=None, **kw):
        """Every warning/error toast also goes to the log; errors stay up longer."""
        if severity in ("warning", "error"):
            log.log(30 if severity == "warning" else 40, "toast: %s%s",
                    f"{title}: " if title else "", message)
        if severity == "error":
            timeout = ERROR_TOAST_SECS if timeout is None else max(timeout, ERROR_TOAST_SECS)
            message = f"{message}\n(details: derot log)"
        return super().notify(message, title=title, severity=severity, timeout=timeout, **kw)

    def trace(self, what: str, exc: BaseException) -> None:
        """Log an unexpected exception with its traceback (call from an except block)."""
        log.error("%s: %s", what, exc, exc_info=exc)

    def _handle_exception(self, error: Exception) -> None:
        log.critical("console crashed", exc_info=error)
        super()._handle_exception(error)

    # ------------------------------------------------------------ layout

    def compose(self) -> ComposeResult:
        # Direct references: the console's widgets must be reachable while a form is on
        # top (App.query_one looks only at the active screen in some Textual versions).
        self.w_summary = Static(id="summary")
        self.w_table: DataTable = DataTable(id="table", cursor_type="row", zebra_stripes=False)
        self.w_empty = Static("no sessions yet — press n to add one", id="empty")
        self.w_detail = Static(id="detail")
        self.w_preview = LiveView(id="preview")
        self.w_preview_box = VerticalScroll(self.w_preview, id="preview-box")
        yield self.w_summary
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield self.w_table
                yield self.w_empty
            with Vertical(id="right"):
                yield self.w_detail
                yield self.w_preview_box
        yield Footer()

    def on_mount(self) -> None:
        table = self.w_table
        for key, label in [("icon", " "), ("name", "Session"), ("where", "Machine"),
                           ("status", "Status")]:
            table.add_column(label, key=key)
        table.focus()
        self.screen.set_class(self.size.width < NARROW_WIDTH, "narrow")
        self.set_interval(PREVIEW_SECS, self.refresh_preview)
        self.statuses = [
            Status(s, self.cfg.host_of(s), self.cfg.account_of(s)) for s in self.cfg.sessions
        ]
        self.render_all()
        if self.created:
            self.notify("Welcome! Press n to add your first session.", timeout=10)
        self._start_timer()
        if self.poll_on_mount:
            self.action_refresh()

    def _start_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_interval(self.cfg.refresh, self.action_refresh)

    # ------------------------------------------------------------ polling

    def action_refresh(self) -> None:
        if self._poll_lock.locked():
            return
        self.poll_worker()

    @work(thread=True, exclusive=False, group="poll")
    def poll_worker(self) -> None:
        if not self._poll_lock.acquire(blocking=False):
            return
        try:
            cfg = self.cfg
            statuses, offline = sessions.poll_full(cfg)
            self.call_from_thread(self.apply_poll, statuses, offline, cfg)
        except Exception as e:  # never crash the UI on a poll error
            self.trace("refresh failed", e)
            self.call_from_thread(self.notify, f"refresh failed: {e}", severity="error")
        finally:
            self._poll_lock.release()

    def apply_poll(self, statuses: List[Status], offline: Dict[str, str],
                   cfg: Optional[Config] = None) -> None:
        if cfg is not None and cfg is not self.cfg:
            return  # config was reloaded while polling; drop stale result
        self.statuses = statuses
        self.offline = offline
        self.updated = time.time()
        self.notifier.update(statuses)
        self.render_all()

    def _toast_alert(self, title: str, body: str) -> None:
        self.notify(body, title=title, timeout=8)

    # ------------------------------------------------------------ rendering

    def on_resize(self, event) -> None:
        self.screen.set_class(event.size.width < NARROW_WIDTH, "narrow")

    def render_all(self) -> None:
        self.render_summary()
        self.render_table()
        self.render_detail()

    def render_summary(self) -> None:
        counts: Dict[str, int] = {}
        for st in self.statuses:
            counts[st.state] = counts.get(st.state, 0) + 1
        t = Text()
        t.append("derot", style="bold")
        words = {"waiting": "need you", "done": "done", "busy": "working", "idle": "idle",
                 "stopped": "stopped"}
        parts = [(f"{counts[k]} {w}", STYLE[k][2]) for k, w in words.items() if counts.get(k)]
        if parts:
            t.append("  ")
            for i, (text, color) in enumerate(parts):
                if i:
                    t.append(" · ", style="dim")
                t.append(text, style=color)
        if self.offline:
            t.append("   ")
            t.append(f"✗ can't reach: {', '.join(self.offline)}", style=STYLE["offline"][2])
        if self.updated:
            t.append(f"   updated {time.strftime('%H:%M:%S', time.localtime(self.updated))}",
                     style="dim")
        self.w_summary.update(t)

    def selected_name(self) -> Optional[str]:
        table = self.w_table
        if not table.row_count:
            return None
        try:
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:
            return None
        return key.value if key is not None else None

    def selected(self) -> Optional[Status]:
        name = self.selected_name()
        for st in self.statuses:
            if st.name == name:
                return st
        return None

    def render_table(self) -> None:
        table = self.w_table
        keep = self.selected_name()
        now = time.time()
        table.clear()
        for st in self.statuses:
            icon, _, color, bold = STYLE[st.state]
            dim = st.state in ("idle", "stopped")
            name = Text(st.name, style="bold" if st.state in ("waiting", "done") else "")
            if st.attached:
                name.append(" ◂", style="dim")
            table.add_row(
                Text(icon, style=f"bold {color}" if bold else color),
                name,
                Text(st.where, style="dim" if dim else ""),
                Text(sessions.status_text(st, now), style=f"bold {color}" if bold else color),
                key=st.name,
            )
        empty = not self.cfg.sessions
        self.w_empty.display = empty
        table.display = not empty
        if keep is not None:
            try:
                table.move_cursor(row=table.get_row_index(keep), animate=False)
            except Exception:
                pass

    def render_detail(self) -> None:
        detail = self.w_detail
        st = self.selected()
        if st is None:
            detail.update(Text("") if self.cfg.sessions else
                          Text(f"config: {self.cfg.path}", style="dim"))
            return
        icon, _, color, _ = STYLE[st.state]
        t = Text()
        t.append(f"{st.name}  ", style="bold")
        t.append(f"{icon} {sessions.status_text(st)}", style=color)
        if st.attached:
            t.append("  (attached elsewhere)", style="dim")
        agent = f" ({st.account.agent_label})" if st.account.agent != "claude" else ""
        t.append(f"\n{st.sdef.dir} · {st.host.label} · {st.account.name}{agent}", style="dim")
        if st.sdef.note:
            t.append(f"\n{st.sdef.note}", style="italic")
        what = sessions.happening(st) if st.state != "busy" else st.message
        if what and what != st.sdef.note:
            # one short line: the full text is in the preview below
            t.append(f"\n{brief(what, 110)}",
                     style=color if st.state in ("waiting", "offline") else "")
        if st.state == "offline":
            hint = "machine unreachable · r: retry"
        elif st.state == "stopped":
            hint = ("enter: start and type · s: start · c: continue last conversation"
                    " · R: pick one to resume · f: full screen")
        elif st.state == "waiting":
            hint = "1-9: pick an option · enter/click: type · f: full screen"
        else:
            hint = (f"enter/click: type · f: full screen ({sessions.key_label(self.cfg.detach_key)}"
                    " returns) · x: stop")
        t.append(f"\n{hint}", style="dim italic")
        detail.update(t)

    # ------------------------------------------------------------ preview

    def preview_kind(self, st: Status) -> str:
        if self.live == st.name or self.preview_mode == "screen" or not st.transcript:
            return "screen"
        if self.preview_mode == "conversation":
            return "conversation"
        # a running session looks exactly as it does when you type into it or attach;
        # the transcript is for sessions that have stopped (nothing left on screen)
        return "screen" if st.running else "conversation"

    def refresh_preview(self) -> None:
        st = self.selected()
        box = self.w_preview_box
        if st is None:
            self.show_preview(None, "", Text(""))
            return
        kind = self.preview_kind(st)
        if kind == "screen" and not st.running:
            box.border_title = "preview"
            self.show_preview((st.name, "none"), "preview",
                              Text("not running — nothing on screen", style="dim"))
            return
        if self._preview_lock.locked():
            return
        region = self.w_preview_box.content_region
        # fit only sessions nobody is looking at; never shrink someone's attached terminal
        fit = None if st.attached else (region.width, region.height)
        self.preview_worker(st.name, kind, st.transcript, fit)

    @work(thread=True, group="preview")
    def preview_worker(self, name: str, kind: str, transcript: str,
                       fit: Optional[tuple] = None) -> None:
        if not self._preview_lock.acquire(blocking=False):
            return
        try:
            items = [] if kind == "screen" else sessions.conversation(self.cfg, name, transcript)
            if kind == "conversation" and not items and self.preview_mode == "auto":
                kind = "screen"  # nothing said yet: the screen is more useful
            if kind == "screen":
                scr = sessions.screen(self.cfg, name)
                if fit and scr.size and scr.size != (max(40, fit[0]), max(10, fit[1])):
                    if sessions.fit(self.cfg, name, *fit):
                        time.sleep(0.3)  # let Claude redraw for the new size
                        scr = sessions.screen(self.cfg, name)
                body = render_screen(scr, cursor=self.live == name)
            else:
                body = render_conversation(items, self.cfg.account_of(self.cfg.session(name)).agent)
        except sessions.SessionError as e:
            body = Text(str(e), style="dim")
        except Exception as e:
            self.trace(f"preview of {name} failed", e)
            body = Text(f"preview failed: {e}", style="dim")
        finally:
            self._preview_lock.release()
        self.call_from_thread(self.show_preview, (name, kind), kind, body)

    def show_preview(self, key: Optional[tuple], kind: str, body: Text) -> None:
        if key is not None and key[0] != self.selected_name():
            # selection moved on while this was loading (and that refresh was skipped
            # because this one held the lock): load the session that's selected now
            self.refresh_preview()
            return
        box = self.w_preview_box
        if self.live and key and key[0] == self.live:
            box.border_title = f"typing into {self.live}  ·  Ctrl-q: stop"
        elif kind in ("conversation", "screen"):
            auto = " (auto)" if self.preview_mode == "auto" else ""
            box.border_title = f"{kind}{auto}  ·  p: switch view  ·  enter/click: type"
        else:
            box.border_title = kind
        if key == self._preview_key and body.plain == self._preview_text:
            return  # unchanged: keep the scroll position
        new_target = key != self._preview_key
        at_end = box.scroll_y >= box.max_scroll_y - 1
        self._preview_key, self._preview_text = key, body.plain
        preview = self.w_preview
        # the session's terminal is wider than this pane: crop its lines instead of wrapping
        preview.set_class(kind == "screen", "screen")
        preview.update(body)
        if at_end or new_target:  # follow new output unless you scrolled up to read
            box.call_after_refresh(box.scroll_end, animate=False)

    def _next_mode(self) -> str:
        return PREVIEW_MODES[(PREVIEW_MODES.index(self.preview_mode) + 1) % len(PREVIEW_MODES)]

    def action_preview_mode(self) -> None:
        self.preview_mode = self._next_mode()
        self._preview_key = None
        self.notify(f"preview: {self.preview_mode}", timeout=2)
        self.refresh_preview()

    # ------------------------------------------------------------ live typing

    def action_live(self) -> None:
        st = self.selected()
        if st is None:
            return
        if not st.running:
            self.notify(f"{st.name} isn't running — press enter, s or c to start it",
                        severity="warning")
            return
        self.live = st.name
        self.w_preview.can_focus = True
        self.w_preview_box.add_class("live")
        self.w_preview_box.border_title = f"typing into {st.name}  ·  Ctrl-q: stop"
        self._preview_key = None
        self.w_preview.focus()
        if self._live_timer is None:
            self._live_timer = self.set_interval(LIVE_SECS, self.refresh_preview)
        else:
            self._live_timer.resume()
        self.refresh_preview()

    def stop_live(self) -> None:
        if not self.live:
            return
        self.live = None
        self.w_preview.can_focus = False
        self.w_preview_box.remove_class("live")
        if self._live_timer is not None:
            self._live_timer.pause()
        self._preview_key = None
        if self.focused is None or self.focused is self.w_preview:
            self.w_table.focus()
        self.refresh_preview()

    def action_ctrl_q(self) -> None:
        if self.live:
            self.stop_live()
        else:
            self.exit()

    def queue_input(self, kind: str, value: str) -> None:
        """Queue typed input for the live session; sent in order by one worker. Each chunk
        keeps its session, so keys typed after switching never go to the previous one."""
        name = self.live
        if not name:
            return
        st = next((st for st in self.statuses if st.name == name), None)
        answer = st is not None and st.state == "waiting" and (
            (kind == "key" and value == "Enter") or (kind == "text" and value.isdigit()))
        with self._input_lock:
            last = self._input[-1] if self._input else None
            if kind == "text" and last and last[:2] == (name, "text"):
                self._input[-1] = (name, "text", last[2] + value)
            else:
                self._input.append((name, kind, value))
            if answer:  # this answers the prompt: flip "needs you" once it's sent
                self._input.append((name, "answered", st.ts))
            if self._sending:
                return
            self._sending = True
        self.input_sender()

    @work(thread=True, group="type")
    def input_sender(self) -> None:
        while True:
            with self._input_lock:
                batch, self._input = self._input, []
                if not batch:
                    self._sending = False
                    return
            groups: List[tuple] = []  # consecutive chunks for the same session
            for name, kind, value in batch:
                if groups and groups[-1][0] == name:
                    groups[-1][1].append((kind, value))
                else:
                    groups.append((name, [(kind, value)]))
            answered = False
            for name, chunks in groups:
                try:
                    sessions.send_input(self.cfg, name,
                                        [c for c in chunks if c[0] != "answered"])
                    for ts in {c[1] for c in chunks if c[0] == "answered"}:
                        sessions.mark_answered(self.cfg, name, ts)
                        answered = True
                except Exception as e:
                    with self._input_lock:
                        self._input, self._sending = [], False
                    if not isinstance(e, sessions.SessionError):
                        self.trace(f"typing into {name} failed", e)
                    self.call_from_thread(self.notify, str(e), severity="error")
                    self.call_from_thread(self.stop_live)
                    return
            self.call_from_thread(self.refresh_preview)
            if answered:
                self.call_from_thread(self.action_refresh)

    # ------------------------------------------------------------ answering prompts

    @work(thread=True, group="send")
    def key_worker(self, name: str, key: str, waiting_ts: Optional[float] = None) -> None:
        try:
            sessions.send_key(self.cfg, name, key)
            if waiting_ts is not None:
                sessions.mark_answered(self.cfg, name, waiting_ts)
        except sessions.SessionError as e:
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        except Exception as e:
            self.trace(f"couldn't send to {name}", e)
            self.call_from_thread(self.notify, f"couldn't send to {name}: {e}", severity="error")
            return
        self.call_from_thread(self.notify, f"sent {key} to {name}", timeout=2)
        time.sleep(0.4)
        self.call_from_thread(self.action_refresh)
        self.call_from_thread(self.refresh_preview)

    def action_press_digit(self, digit: str) -> None:
        st = self.selected()
        if st is None or not st.running:
            return
        self.key_worker(st.name, digit, st.ts if st.state == "waiting" else None)

    def check_action(self, action: str, parameters) -> Optional[bool]:
        # Enter is a priority binding for the list; in a form or while typing live it must
        # reach the form / the session instead.
        if action == "open" and (len(self.screen_stack) > 1 or self.live):
            return False
        if action == "press_digit" and (self.live or not self._selected_waiting()):
            return False
        if action == "command_palette" and self.live:
            return False  # Ctrl-P is Claude's (history), not Textual's palette, while live
        return True

    def _selected_waiting(self) -> bool:
        st = self.selected()
        return st is not None and st.state == "waiting"

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.render_detail()
        if event.row_key is not None and (self._preview_key or (None,))[0] != event.row_key.value:
            # never leave the last session's screen under this session's header
            self.show_preview((event.row_key.value, "loading"), "preview",
                              Text("loading…", style="dim"))
            self.refresh_preview()

    def on_click(self, event: events.Click) -> None:
        """A click on the right panel (details or preview) starts typing into the session."""
        if self.live or len(self.screen_stack) > 1:
            return
        if event.widget in (self.w_detail, self.w_preview, self.w_preview_box):
            self.action_open()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # a click on the selected row only selects it (Enter is the priority binding
        # above, so this is never the keyboard)
        event.stop()

    # ------------------------------------------------------------ actions

    def action_open(self) -> None:
        """Enter (and a click on the right panel): type into the session, starting it
        first if it's stopped."""
        st = self.selected()
        if st is None:
            return
        if st.state == "offline":
            self.notify(f"{st.host.name} is unreachable: {st.message}", severity="error")
        elif st.running:
            self.action_live()
        else:
            self.start_worker(st.name, False, then="type")

    def action_fullscreen(self) -> None:
        """f: Claude's own full-screen UI in this terminal (attach); Ctrl-q comes back."""
        st = self.selected()
        if st is None:
            return
        if st.state == "offline":
            self.notify(f"{st.host.name} is unreachable: {st.message}", severity="error")
        elif st.running:
            self.attach(st.name)
        else:
            self.start_worker(st.name, False, then="attach")

    def _type_after_start(self, name: str) -> None:
        for st in self.statuses:
            if st.name == name and not st.running:
                st.state = "idle"  # it's running now; the next poll fills in the rest
        self.render_all()
        if self.selected_name() == name and not self.live and len(self.screen_stack) == 1:
            self.action_live()
        self.action_refresh()

    def action_start(self) -> None:
        self._start_stopped(False)

    def action_continue(self) -> None:
        self._start_stopped(True)

    def action_resume(self) -> None:
        st = self._stopped_selection()
        if st is None:
            return

        def picked(conv_id: Optional[str]) -> None:
            if conv_id:
                self.start_worker(st.name, False, resume=conv_id)

        self.push_screen(ResumePicker(self.cfg, st.name, st.session_id), picked)

    def _stopped_selection(self) -> Optional[Status]:
        st = self.selected()
        if st is None:
            return None
        if st.state == "offline":
            self.notify(f"{st.host.name} is unreachable", severity="error")
        elif st.running:
            self.notify(f"{st.name} is already running", severity="warning")
        else:
            return st
        return None

    def _start_stopped(self, cont: bool) -> None:
        st = self._stopped_selection()
        if st is None:
            return
        if cont and st.session_id:
            # this session's own last conversation, not just the folder's newest
            self.start_worker(st.name, True, resume=st.session_id, resume_file=st.transcript)
        else:
            self.start_worker(st.name, cont)

    @work(thread=True, group="start")
    def start_worker(self, name: str, cont: bool, then: str = "", resume: str = "",
                     resume_file: str = "") -> None:
        """Start a session, then: "type" (Enter) types into it, "attach" (f) goes full
        screen; s / c / R just keep you here, watching it in the preview."""
        self.call_from_thread(self.notify, f"starting {name}…", timeout=2)
        try:
            s = self.cfg.session(name)
            if not installer.ensure_hooks(self.cfg, self.cfg.host_of(s),
                                          self.cfg.account_of(s)):
                self.call_from_thread(
                    self.notify, f"status hooks for {s.account} on {s.host} couldn't be set "
                    "up, so its status may stay idle (details: derot log)",
                    severity="warning", timeout=12)
            sessions.start(self.cfg, name, cont, resume, resume_file)
        except sessions.SessionError as e:  # already logged with full stderr
            self.call_from_thread(self.notify, str(e), severity="error")
            return
        except Exception as e:
            self.trace(f"couldn't start {name}", e)
            self.call_from_thread(self.notify, f"couldn't start {name}: {e}", severity="error")
            return
        if then == "attach":
            self.call_from_thread(self.attach, name)
            return
        if then == "type":
            self.call_from_thread(self._type_after_start, name)
            return
        self.call_from_thread(self.notify, f"started {name} · enter/click: type · "
                              "f: full screen", timeout=4)
        self.call_from_thread(self.action_refresh)

    def attach(self, name: str) -> None:
        try:
            with self.suspend():
                sessions.attach(self.cfg, name)
        except Exception as e:
            self.trace(f"couldn't attach to {name}", e)
            self.notify(f"couldn't attach to {name}: {e}", severity="error")
        self.action_refresh()

    def action_stop(self) -> None:
        st = self.selected()
        if st is None:
            return
        if not st.running:
            self.notify(f"{st.name} is not running", severity="warning")
            return
        now = time.monotonic()
        armed = self._stop_armed
        if armed and armed[0] == st.name and now - armed[1] <= STOP_CONFIRM_SECS:
            self._stop_armed = None
            self.stop_worker(st.name)
            return
        self._stop_armed = (st.name, now)
        warn = ""
        if st.state == "busy":
            warn = " It's still working!"
        elif st.state == "waiting":
            warn = " It's waiting for you!"
        self.notify(f"Press x again to stop {st.name}.{warn}",
                    severity="warning" if warn else "information", timeout=STOP_CONFIRM_SECS)

    @work(thread=True, group="stop")
    def stop_worker(self, name: str) -> None:
        try:
            sessions.stop(self.cfg, name)
            self.call_from_thread(self.notify, f"stopped {name}")
        except sessions.SessionError as e:
            self.call_from_thread(self.notify, str(e), severity="error")
        except Exception as e:
            self.trace(f"couldn't stop {name}", e)
            self.call_from_thread(self.notify, f"couldn't stop {name}: {e}", severity="error")
        self.call_from_thread(self.action_refresh)

    def action_edit(self) -> None:
        path = self.cfg.path or config_mod.config_path()
        try:
            with self.suspend():
                subprocess.call([*find_editor(), str(path)])
        except Exception as e:
            self.trace("couldn't open editor", e)
            self.notify(f"couldn't open editor: {e}", severity="error")
            return
        self.reload_config(path)

    def reload_config(self, path) -> None:
        try:
            cfg = config_mod.load(path)
        except ConfigError as e:
            self.notify(f"config not reloaded: {e}", severity="error", timeout=12)
            return
        old = self.cfg
        self.use_config(cfg)
        self.notify("config reloaded")
        hosts = new_pairs(old, cfg)  # hand-edited accounts need hooks too
        if hosts:
            self.install_hooks_worker(hosts)

    def use_config(self, cfg: Config) -> None:
        old_refresh = self.cfg.refresh
        self.cfg = cfg
        self.notifier.settings = cfg.notify
        names = {s.name for s in cfg.sessions}
        self.statuses = [st for st in self.statuses if st.name in names]
        known = {st.name for st in self.statuses}
        self.statuses += [Status(s, cfg.host_of(s), cfg.account_of(s))
                          for s in cfg.sessions if s.name not in known]
        if cfg.refresh != old_refresh:
            self._start_timer()
        self.render_all()
        self.action_refresh()

    # ------------------------------------------------------------ config forms

    def action_new_session(self) -> None:
        self.push_screen(SessionForm(self.cfg), self._session_saved)

    def action_edit_session(self) -> None:
        st = self.selected()
        if st is None:
            self.action_new_session()
            return
        self.push_screen(SessionForm(self.cfg, st.name, running=st.running),
                         self._session_saved)

    def _session_saved(self, new: Optional[Config]) -> None:
        if new is None:
            return
        old = self.cfg
        if not self.save_config(new):
            return
        added = [s.name for s in new.sessions if s.name not in {x.name for x in old.sessions}]
        if added:
            self.select(added[0])
        self.notify(f"saved {added[0]}" if added else "saved")
        hosts = new_pairs(old, new)
        if hosts:
            self.install_hooks_worker(hosts)
        new_accounts = [a for a in new.accounts if a not in old.accounts]
        for name in new_accounts:
            acct = new.accounts[name]
            if {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"} & set(acct.env):
                continue
            host = next((s.host for s in new.sessions if s.account == name), "local")
            how = ("`codex login` will run: finish signing in to come back."
                   if acct.agent == "codex" else
                   "Claude Code will open: type /login, then /exit to come back.")
            self.push_screen(
                Confirm(f"Log in to the new account “{name}” on {host} now?\n{how}",
                        yes="Log in now", no="Later"),
                lambda ok, n=name, h=host: ok and self.login(n, h))

    def save_config(self, new: Config) -> bool:
        try:
            saved = config_mod.save(new, self.cfg.path or config_mod.config_path())
        except (ConfigError, OSError) as e:
            self.notify(f"couldn't save: {e}", severity="error", timeout=12)
            return False
        self.use_config(saved)
        return True

    def select(self, name: str) -> None:
        table = self.w_table
        try:
            table.move_cursor(row=table.get_row_index(name), animate=False)
        except Exception:
            pass

    def action_remove_session(self) -> None:
        st = self.selected()
        if st is None:
            return
        if st.running:
            self.notify(f"{st.name} is running. Stop it first (x x).", severity="warning")
            return

        def done(ok: bool) -> None:
            if not ok:
                return
            old = self.cfg
            new = copy.deepcopy(old)
            new.sessions = [s for s in new.sessions if s.name != st.name]
            if self.save_config(new):
                self.forget_worker(old, st.name)
                self.notify(f"removed {st.name} (its conversations are kept by "
                            f"{st.account.agent_label})")

        self.push_screen(Confirm(f"Remove “{st.name}” from derot?", yes="Remove"), done)

    @work(thread=True, group="forget")
    def forget_worker(self, cfg: Config, name: str) -> None:
        try:
            sessions.forget(cfg, name)
        except Exception as e:
            self.trace(f"couldn't clean up {name}", e)

    @work(thread=True, group="hooks")
    def install_hooks_worker(self, host_names: List[str]) -> None:
        cfg = self.cfg
        for name in host_names:
            host = cfg.hosts[name]
            lines: List[str] = []
            try:
                ok = installer.setup_host(cfg, host, False, lines.append)
            except Exception as e:
                self.trace(f"hook setup on {name} crashed", e)
                ok, lines = False, [str(e)]
            if ok:
                self.call_from_thread(self.notify, f"status hooks ready on {name}")
            else:
                bad = [ln.strip() for ln in lines if "✗" in ln] or lines[-1:]
                self.call_from_thread(
                    self.notify, f"hook setup on {name} failed: {'; '.join(bad)} (press u)",
                    severity="error", timeout=15)
        self.call_from_thread(self.action_refresh)

    def action_login(self) -> None:
        st = self.selected()
        if st is None:
            self.notify("select a session first", severity="warning")
            return
        self.login(st.account.name, st.host.name)

    def login(self, account: str, host: str) -> None:
        try:
            with self.suspend():
                if self.cfg.accounts[account].agent == "codex":
                    remote_host = not self.cfg.hosts[host].is_local
                    how = "codex login --device-auth" if remote_host else "codex login"
                    print(f"Running `{how}` for account {account} on {host}.")
                    if remote_host:
                        print("Open the link it shows on any device and enter the code.")
                    print("Finish signing in; you'll come back to derot when it's done.\n")
                else:
                    print(f"Opening Claude Code for account {account} on {host}.")
                    print("Type /login to sign in, then /exit to come back to derot.\n")
                sessions.login(self.cfg, account, host)
        except Exception as e:
            self.trace("couldn't open login", e)
            self.notify(f"couldn't open login: {e}", severity="error")

    def action_setup(self) -> None:
        try:
            with self.suspend():
                print("Running derot setup…\n")
                try:
                    installer.setup(self.cfg)
                except Exception as e:
                    self.trace("setup failed", e)
                    print(f"setup failed: {e}")
                try:
                    input("\nPress Enter to go back ")
                except EOFError:
                    pass
        except Exception as e:
            self.trace("couldn't run setup", e)
            self.notify(f"couldn't run setup: {e}", severity="error")
        self.action_refresh()


def run(cfg: Config, created: bool = False) -> None:
    Derot(cfg, created=created).run()
