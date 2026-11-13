"""Curses terminal adapter and live refresh loop for Kanjo TUI."""

from __future__ import annotations

from datetime import datetime, timezone
import math
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import curses
    HAVE_CURSES = True
except ImportError:
    curses = None
    HAVE_CURSES = False

from .model import (
    AntigravityAccountsSection, FilteredData, TimeRange, ViewMode,
    RANGE_TABS, VIEW_MODES,
    build_agent_rows, build_antigravity_accounts_section, build_day_rows,
    build_model_rows, build_project_detail, build_project_footer_rows,
    build_project_rows, build_subscription_meters, build_total_view_model,
    filter_report, get_tz
)
from .render import Canvas, Style, TUIState, render_ui
from .static import rgb_to_256, NAMED_FG, NAMED_BG


class ColorManager:
    """Manages curses color pairs safely."""
    def __init__(self, no_color: bool = False):
        self.no_color = no_color
        self.can_color = False
        self.colors_256 = False
        self.pair_cache: Dict[Tuple[int, int], int] = {}
        self.next_pair = 1

        if not no_color and HAVE_CURSES:
            try:
                if curses.has_colors():
                    curses.start_color()
                    curses.use_default_colors()
                    self.can_color = True
                    self.colors_256 = (getattr(curses, "COLORS", 0) >= 256)
            except Exception:
                self.can_color = False

    def color_to_curses(self, c: Any, is_bg: bool = False) -> int:
        if not self.can_color:
            return -1
        if isinstance(c, tuple) and len(c) == 3:
            r, g, b = c
            if self.colors_256:
                return rgb_to_256(r, g, b)
            # 8-color fallback
            # Grayscale or primary
            rg = 1 if r > 128 else 0
            gg = 1 if g > 128 else 0
            bg_b = 1 if b > 128 else 0
            code = (rg << 0) | (gg << 1) | (bg_b << 2)
            # Map RGB bitmask to curses colors:
            # 0: black, 1: red, 2: green, 3: yellow, 4: blue, 5: magenta, 6: cyan, 7: white
            mapping = [
                curses.COLOR_BLACK, curses.COLOR_RED, curses.COLOR_GREEN,
                curses.COLOR_YELLOW, curses.COLOR_BLUE, curses.COLOR_MAGENTA,
                curses.COLOR_CYAN, curses.COLOR_WHITE
            ]
            return mapping[code & 7]
        if isinstance(c, str):
            c_low = c.lower()
            if c_low in ("black",): return curses.COLOR_BLACK
            if c_low in ("red",): return curses.COLOR_RED
            if c_low in ("green",): return curses.COLOR_GREEN
            if c_low in ("yellow",): return curses.COLOR_YELLOW
            if c_low in ("blue",): return curses.COLOR_BLUE
            if c_low in ("magenta",): return curses.COLOR_MAGENTA
            if c_low in ("cyan",): return curses.COLOR_CYAN
            if c_low in ("white",): return curses.COLOR_WHITE
            if c_low in ("gray", "grey"): return 8 if self.colors_256 else curses.COLOR_BLACK
        if isinstance(c, int):
            return c
        return -1

    def get_pair(self, style: Style) -> int:
        if not self.can_color or self.no_color:
            return 0
        fg = self.color_to_curses(style.fg, is_bg=False)
        bg = self.color_to_curses(style.bg, is_bg=True)
        if fg == -1 and bg == -1:
            return 0
        key = (fg, bg)
        if key in self.pair_cache:
            return self.pair_cache[key]
        max_pairs = min(getattr(curses, "COLOR_PAIRS", 256) - 1, 255)
        if self.next_pair >= max_pairs:
            return 0
        pair_id = self.next_pair
        self.next_pair += 1
        try:
            curses.init_pair(pair_id, fg, bg)
            self.pair_cache[key] = pair_id
            return pair_id
        except Exception:
            return 0


class BackgroundScanner:
    """Runs Kanjo scans in the background and keeps session cache warm."""
    def __init__(self, config=None, cache=None, interval: float = 60.0,
                 data_path: Optional[str] = None, use_cache: bool = True):
        self.config = config
        self.cache = cache
        self.interval = max(5.0, interval)
        self.data_path = data_path
        self.use_cache = use_cache
        self.latest_doc: Optional[dict] = None
        self.antigravity_accounts_data: Optional[Any] = None
        self.current_account: Optional[str] = None
        self.is_scanning = False
        self.last_scan_time = ""
        self._trigger = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._trigger.set()

    def refresh_now(self) -> None:
        self._trigger.set()

    def _run(self) -> None:
        if self.data_path:
            while not self._stop.is_set():
                self._trigger.wait(timeout=self.interval)
                self._trigger.clear()
            return

        from ..export import build_export, source_fingerprint, save_fast_export, scan
        from ..antigravity_accounts import get_account_index, compute_antigravity_accounts_window
        from ..sources import antigravity

        while not self._stop.is_set():
            with self._lock:
                self.is_scanning = True
            try:
                # Run export scan
                doc = build_export(config=self.config, cache=self.cache)
                now_str = datetime.now().strftime("%H:%M:%S")

                cur_acc = None
                try:
                    idx = get_account_index()
                    cur_acc = idx.get_current_account()
                except Exception:
                    pass

                ag_accounts = None
                if doc and isinstance(doc.get("antigravity_accounts"), dict):
                    ag_accounts = doc["antigravity_accounts"]
                    cur_acc = ag_accounts.get("current") or cur_acc
                else:
                    try:
                        roots = antigravity.roots()
                        scan_res = scan({"antigravity": roots}, cache=self.cache)
                        if scan_res.sessions:
                            ag_accounts = compute_antigravity_accounts_window(
                                scan_res.sessions, doc or {}, current_account=cur_acc
                            )
                    except Exception:
                        pass

                with self._lock:
                    self.latest_doc = doc
                    self.current_account = cur_acc
                    self.antigravity_accounts_data = ag_accounts
                    self.last_scan_time = now_str
                    self.is_scanning = False

                if self.use_cache and doc is not None:
                    try:
                        fp = source_fingerprint(config=self.config)
                        save_fast_export(fp, doc)
                    except Exception:
                        pass
            except Exception:
                with self._lock:
                    self.is_scanning = False

            # Wait for interval or immediate trigger
            self._trigger.wait(timeout=self.interval)
            self._trigger.clear()


def run_curses_tui(
    stdscr,
    initial_doc: Optional[dict] = None,
    config=None,
    cache=None,
    interval: float = 60.0,
    time_range: TimeRange = TimeRange.ALL,
    view_mode: ViewMode = ViewMode.PROJECTS,
    ascii_mode: bool = False,
    no_color: bool = False,
    version: str = "0.9.0",
    antigravity_accounts_data: Optional[Any] = None,
    current_account: Optional[str] = None,
    data_path: Optional[str] = None,
    use_cache: bool = True
) -> int:
    """Main interactive curses loop."""
    # Setup curses
    try:
        curses.curs_set(0)
    except Exception:
        pass
    stdscr.timeout(50)  # 50ms poll
    stdscr.keypad(True)

    color_mgr = ColorManager(no_color=no_color)

    # Start background scanner
    scanner = BackgroundScanner(
        config=config, cache=cache, interval=interval,
        data_path=data_path, use_cache=use_cache
    )
    scanner.latest_doc = initial_doc
    scanner.last_scan_time = datetime.now().strftime("%H:%M:%S") if initial_doc else ""
    scanner.is_scanning = (initial_doc is None)
    scanner.antigravity_accounts_data = antigravity_accounts_data
    scanner.current_account = current_account
    scanner.start()

    state = TUIState(
        version=version,
        time_range=time_range,
        view_mode=view_mode,
        ascii_mode=ascii_mode,
        no_color=no_color,
        is_scanning=(initial_doc is None),
        last_refresh_time=scanner.last_scan_time,
    )

    last_spinner_tick = time.time()

    def get_sort_key(row, col):
        if isinstance(row, ProjectRowViewModel):
            if col == "tokens":
                from .model import parse_tokens_str
                return parse_tokens_str(row.tokens_str)
            if col == "sessions":
                try: return int(row.sessions_str)
                except ValueError: return 0
            if col == "name":
                return row.name.lower()
            # default cost
            try: return float(row.cost_str.replace("$", "").replace(",", ""))
            except ValueError: return 0.0
        return 0

    try:
        while True:
            # Check background scan results
            with scanner._lock:
                doc = scanner.latest_doc or initial_doc
                state.is_scanning = scanner.is_scanning
                if scanner.last_scan_time:
                    state.last_refresh_time = scanner.last_scan_time
                if scanner.antigravity_accounts_data:
                    antigravity_accounts_data = scanner.antigravity_accounts_data
                if scanner.current_account:
                    current_account = scanner.current_account

            # Spinner update
            now_ts = time.time()
            if now_ts - last_spinner_tick > 0.1:
                state.spinner_frame = (state.spinner_frame + 1) % 60
                last_spinner_tick = now_ts

            # Screen dimensions
            scr_h, scr_w = stdscr.getmaxyx()
            canvas = Canvas(scr_w, scr_h)

            if doc is None:
                render_ui(
                    canvas=canvas,
                    state=state,
                    filtered=None,
                    static_mode=False,
                )
            else:
                tz = get_tz(doc)
                if data_path and doc.get("generated_at"):
                    from .model import parse_iso_dt
                    now_dt = parse_iso_dt(doc.get("generated_at"), default_tz=tz) or datetime.now(tz)
                else:
                    now_dt = datetime.now(tz)

                filtered = filter_report(doc, state.time_range, now=now_dt)
                total_vm = build_total_view_model(filtered)
                meters = build_subscription_meters(doc, now=now_dt)
                accounts_sec = build_antigravity_accounts_section(
                    doc, now=now_dt,
                    antigravity_data=antigravity_accounts_data,
                    current_account=current_account
                )

                query = state.filter_query if not state.filter_active else state.filter_input
                proj_rows = build_project_rows(filtered, now_dt, tz, ascii_mode=state.ascii_mode, filter_query=query)
                proj_footers = build_project_footer_rows(filtered, now_dt, tz, ascii_mode=state.ascii_mode)
                model_rows = build_model_rows(filtered, filter_query=query)
                agent_rows = build_agent_rows(filtered, filter_query=query)
                day_rows = build_day_rows(filtered, filter_query=query)

                # Apply sorting if requested
                if state.view_mode == ViewMode.PROJECTS and state.sort_column != "cost":
                    proj_rows.sort(key=lambda r: get_sort_key(r, state.sort_column), reverse=state.sort_descending)

                detail_vm = None
                if state.detail_open and state.detail_project:
                    detail_vm = build_project_detail(state.detail_project, now_dt, tz, ascii_mode=state.ascii_mode)

                # Render onto canvas
                render_ui(
                    canvas=canvas,
                    state=state,
                    filtered=filtered,
                    total_vm=total_vm,
                    meters=meters,
                    accounts_section=accounts_sec,
                    project_rows=proj_rows,
                    project_footers=proj_footers,
                    model_rows=model_rows,
                    agent_rows=agent_rows,
                    day_rows=day_rows,
                    detail_vm=detail_vm,
                    static_mode=False,
                )

            # Draw Canvas onto curses screen
            stdscr.erase()
            for y in range(min(canvas.height, scr_h)):
                row = canvas.grid[y]
                x = 0
                while x < min(canvas.width, scr_w):
                    cell = row[x]
                    if cell.char == "":
                        x += 1
                        continue
                    attrs = curses.A_NORMAL
                    if cell.style.bold:
                        attrs |= curses.A_BOLD
                    if cell.style.dim:
                        attrs |= curses.A_DIM
                    if cell.style.inverse:
                        attrs |= curses.A_REVERSE
                    if cell.style.underline:
                        attrs |= curses.A_UNDERLINE
                    pair = color_mgr.get_pair(cell.style)
                    if pair > 0:
                        attrs |= curses.color_pair(pair)

                    # Avoid lower right corner glitch
                    if y == scr_h - 1 and x >= scr_w - 1:
                        try:
                            stdscr.insch(y, x, cell.char, attrs)
                        except Exception:
                            pass
                    else:
                        try:
                            stdscr.addstr(y, x, cell.char, attrs)
                        except Exception:
                            pass
                    x += 1

            try:
                stdscr.noutrefresh()
                curses.doupdate()
            except Exception:
                pass

            # Handle keyboard input
            try:
                ch = stdscr.getch()
            except curses.error:
                continue

            if ch == -1:
                continue

            # Handle Help mode
            if state.show_help:
                state.show_help = False
                continue

            # Handle Filter input mode
            if state.filter_active:
                if ch in (curses.KEY_BACKSPACE, 127, 8):
                    state.filter_input = state.filter_input[:-1]
                elif ch in (10, 13, curses.KEY_ENTER):
                    state.filter_query = state.filter_input
                    state.filter_active = False
                    state.selected_index = 0
                    state.scroll_top = 0
                elif ch == 27:  # Esc
                    state.filter_active = False
                    state.filter_input = state.filter_query
                elif 32 <= ch <= 126:
                    state.filter_input += chr(ch)
                continue

            # Terminal resize
            if ch == curses.KEY_RESIZE:
                try:
                    h, w = stdscr.getmaxyx()
                    curses.resizeterm(h, w)
                except Exception:
                    pass
                continue

            # Normal key bindings
            if ch in (ord('q'), ord('Q'), getattr(curses, "KEY_F10", -999)):
                break

            # Range switching (1-6)
            if ord('1') <= ch <= ord('6'):
                idx = ch - ord('1')
                if 0 <= idx < len(RANGE_TABS):
                    state.time_range = RANGE_TABS[idx][0]
                    state.selected_index = 0
                    state.scroll_top = 0
                continue

            # Range left / right arrows
            if ch in (curses.KEY_LEFT,):
                cur_idx = next((i for i, t in enumerate(RANGE_TABS) if t[0] == state.time_range), 0)
                next_idx = (cur_idx - 1) % len(RANGE_TABS)
                state.time_range = RANGE_TABS[next_idx][0]
                state.selected_index = 0
                state.scroll_top = 0
                continue
            if ch in (curses.KEY_RIGHT, getattr(curses, "KEY_F2", -999)):
                cur_idx = next((i for i, t in enumerate(RANGE_TABS) if t[0] == state.time_range), 0)
                next_idx = (cur_idx + 1) % len(RANGE_TABS)
                state.time_range = RANGE_TABS[next_idx][0]
                state.selected_index = 0
                state.scroll_top = 0
                continue

            # Views switching (Tab or F3 or p/m/a/d)
            if ch in (ord('\t'), getattr(curses, "KEY_F3", -999)):
                cur_v_idx = next((i for i, v in enumerate(VIEW_MODES) if v[0] == state.view_mode), 0)
                next_v_idx = (cur_v_idx + 1) % len(VIEW_MODES)
                state.view_mode = VIEW_MODES[next_v_idx][0]
                state.selected_index = 0
                state.scroll_top = 0
                continue
            if ch == ord('p'):
                state.view_mode = ViewMode.PROJECTS
                state.selected_index = 0
                state.scroll_top = 0
                continue
            if ch == ord('m'):
                state.view_mode = ViewMode.MODELS
                state.selected_index = 0
                state.scroll_top = 0
                continue
            if ch == ord('a'):
                state.view_mode = ViewMode.AGENTS
                state.selected_index = 0
                state.scroll_top = 0
                continue
            if ch == ord('d'):
                state.view_mode = ViewMode.DAYS
                state.selected_index = 0
                state.scroll_top = 0
                continue

            # Meters expanded (M or F7)
            if ch in (ord('M'), getattr(curses, "KEY_F7", -999)):
                state.meters_expanded = not state.meters_expanded
                continue

            # Help (? or F1)
            if ch in (ord('?'), getattr(curses, "KEY_F1", -999)):
                state.show_help = True
                continue

            # Refresh (r or F5)
            if ch in (ord('r'), ord('R'), getattr(curses, "KEY_F5", -999)):
                scanner.refresh_now()
                continue

            # Filter (/ or F4)
            if ch in (ord('/'), getattr(curses, "KEY_F4", -999)):
                state.filter_active = True
                state.filter_input = state.filter_query
                continue

            # Sort (s or F6)
            if ch in (ord('s'), ord('S'), getattr(curses, "KEY_F6", -999)):
                if state.view_mode == ViewMode.PROJECTS:
                    cols = ["cost", "tokens", "sessions", "name"]
                    c_idx = cols.index(state.sort_column) if state.sort_column in cols else 0
                    state.sort_column = cols[(c_idx + 1) % len(cols)]
                    state.selected_index = 0
                    state.scroll_top = 0
                continue

            # Navigation: Up, Down, PageUp, PageDown, Home, End
            cur_list_len = len(proj_rows) if state.view_mode == ViewMode.PROJECTS else (
                len(model_rows) if state.view_mode == ViewMode.MODELS else (
                    len(agent_rows) if state.view_mode == ViewMode.AGENTS else len(day_rows)
                )
            )

            if ch == curses.KEY_UP:
                if state.selected_index > 0:
                    state.selected_index -= 1
                continue
            if ch == curses.KEY_DOWN:
                if state.selected_index < cur_list_len - 1:
                    state.selected_index += 1
                continue
            if ch == curses.KEY_PPAGE:  # PgUp
                state.selected_index = max(0, state.selected_index - 10)
                continue
            if ch == curses.KEY_NPAGE:  # PgDn
                state.selected_index = min(max(0, cur_list_len - 1), state.selected_index + 10)
                continue
            if ch in (curses.KEY_HOME, ord('g')):
                state.selected_index = 0
                continue
            if ch in (curses.KEY_END, ord('G')):
                state.selected_index = max(0, cur_list_len - 1)
                continue

            # Enter on Project -> Detail pane
            if ch in (10, 13, curses.KEY_ENTER):
                if state.view_mode == ViewMode.PROJECTS and proj_rows:
                    if 0 <= state.selected_index < len(filtered.projects):
                        state.detail_project = filtered.projects[state.selected_index]
                        state.detail_open = True
                continue

            # Esc or Backspace
            if ch in (27, curses.KEY_BACKSPACE, 127, 8):
                if state.detail_open:
                    state.detail_open = False
                    state.detail_project = None
                elif state.filter_query:
                    state.filter_query = ""
                    state.selected_index = 0
                    state.scroll_top = 0
                elif ch == 27:
                    # Standalone Esc when nothing is open: quit cleanly
                    break
                continue

    finally:
        # Cleanup background scanner
        scanner.stop()
    return 0
