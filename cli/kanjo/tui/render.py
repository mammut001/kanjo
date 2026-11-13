"""Pure Canvas abstraction and view-model rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import textwrap
from typing import Any, Dict, List, Optional, Tuple, Union
import unicodedata

from .model import (
    AntigravityAccountsSection, DayRowViewModel, FilteredData, ModelRowViewModel,
    ProjectDetailViewModel, ProjectRowViewModel, QuotaLevel, QuotaMeterWindow,
    RANGE_TABS, SubscriptionMeter, TimeRange, TotalViewModel, VIEW_MODES, ViewMode,
    format_money, format_tokens, agent_color
)

# Text / Display Width Helpers

def char_width(ch: str) -> int:
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    w = unicodedata.east_asian_width(ch)
    return 2 if w in ("W", "F") else 1


def str_width(s: str) -> int:
    return sum(char_width(ch) for ch in s)


def truncate_str(s: str, max_width: int, ellipsis: str = "…") -> str:
    if max_width <= 0:
        return ""
    if str_width(s) <= max_width:
        return s
    ew = str_width(ellipsis)
    target = max_width - ew
    if target <= 0:
        # Just grab characters up to max_width
        res = []
        cur = 0
        for ch in s:
            cw = char_width(ch)
            if cur + cw > max_width:
                break
            res.append(ch)
            cur += cw
        return "".join(res)
    res = []
    cur = 0
    for ch in s:
        cw = char_width(ch)
        if cur + cw > target:
            break
        res.append(ch)
        cur += cw
    return "".join(res) + ellipsis


def pad_str(s: str, width: int, align: str = "left") -> str:
    """Pad string to exact display width (handling wide characters)."""
    sw = str_width(s)
    if sw >= width:
        return s
    pad = " " * (width - sw)
    if align == "right":
        return pad + s
    if align == "center":
        left = len(pad) // 2
        right = len(pad) - left
        return (" " * left) + s + (" " * right)
    return s + pad


# Style & Canvas

@dataclass(frozen=True)
class Style:
    fg: Optional[Union[Tuple[int, int, int], str, int]] = None
    bg: Optional[Union[Tuple[int, int, int], str, int]] = None
    bold: bool = False
    dim: bool = False
    inverse: bool = False
    underline: bool = False

    def normalized(self) -> "Style":
        if self.inverse and (self.fg is not None or self.bg is not None):
            return Style(bold=self.bold, dim=self.dim, underline=self.underline)
        return self


@dataclass
class Cell:
    char: str = " "
    style: Style = field(default_factory=Style)

    def __post_init__(self) -> None:
        self.style = self.style.normalized()


class Canvas:
    def __init__(self, width: int, height: int):
        self.width = max(1, width)
        self.height = max(1, height)
        self.grid: List[List[Cell]] = [
            [Cell(" ", Style()) for _ in range(self.width)]
            for _ in range(self.height)
        ]

    def set_cell(self, x: int, y: int, char: str, style: Style = Style()) -> None:
        if 0 <= y < self.height and 0 <= x < self.width:
            self.grid[y][x] = Cell(char, style)

    def draw_text(self, x: int, y: int, text: str, style: Style = Style(),
                  max_width: Optional[int] = None) -> int:
        """Draw text starting at (x, y). Wide characters take 2 columns.
        Returns the new x position.
        """
        if y < 0 or y >= self.height or x >= self.width:
            return x
        limit = self.width
        if max_width is not None:
            limit = min(limit, x + max_width)

        cur_x = x
        for ch in text:
            cw = char_width(ch)
            if cw == 0:
                continue
            if cur_x + cw > limit:
                break
            if cur_x >= 0:
                self.grid[y][cur_x] = Cell(ch, style)
                if cw == 2 and cur_x + 1 < limit:
                    # Second column of wide character is a continuation cell
                    self.grid[y][cur_x + 1] = Cell("", style)
            cur_x += cw
        return cur_x

    def fill_rect(self, x: int, y: int, w: int, h: int, char: str = " ",
                  style: Style = Style()) -> None:
        for cy in range(max(0, y), min(self.height, y + h)):
            for cx in range(max(0, x), min(self.width, x + w)):
                self.grid[cy][cx] = Cell(char, style)

    def draw_hline(self, x: int, y: int, w: int, char: str = "─",
                   style: Style = Style()) -> None:
        if 0 <= y < self.height:
            cw = char_width(char)
            cur_x = x
            while cur_x < x + w and cur_x + cw <= self.width:
                if cur_x >= 0:
                    self.grid[y][cur_x] = Cell(char, style)
                    if cw == 2 and cur_x + 1 < self.width:
                        self.grid[y][cur_x + 1] = Cell("", style)
                cur_x += max(1, cw)

    def draw_box(self, x: int, y: int, w: int, h: int, title: Optional[str] = None,
                 style: Style = Style(), border_style: Style = Style(),
                 ascii_mode: bool = False) -> None:
        tl = "+" if ascii_mode else "┌"
        tr = "+" if ascii_mode else "┐"
        bl = "+" if ascii_mode else "└"
        br = "+" if ascii_mode else "┘"
        hl = "-" if ascii_mode else "─"
        vl = "|" if ascii_mode else "│"

        # Fill background
        self.fill_rect(x, y, w, h, " ", style)

        # Corners & borders
        self.set_cell(x, y, tl, border_style)
        self.set_cell(x + w - 1, y, tr, border_style)
        self.set_cell(x, y + h - 1, bl, border_style)
        self.set_cell(x + w - 1, y + h - 1, br, border_style)

        self.draw_hline(x + 1, y, w - 2, hl, border_style)
        self.draw_hline(x + 1, y + h - 1, w - 2, hl, border_style)

        for cy in range(y + 1, y + h - 1):
            self.set_cell(x, cy, vl, border_style)
            self.set_cell(x + w - 1, cy, vl, border_style)

        if title:
            title_text = f" {title} "
            self.draw_text(x + 2, y, title_text, Style(bold=True, fg=border_style.fg), max_width=w - 4)

    def get_line_cells(self, y: int) -> List[Cell]:
        if 0 <= y < self.height:
            return self.grid[y]
        return []

    def get_line_text(self, y: int) -> str:
        if 0 <= y < self.height:
            return "".join(c.char for c in self.grid[y])
        return ""


# State container for TUI

@dataclass
class TUIState:
    version: str
    time_range: TimeRange = TimeRange.ALL
    view_mode: ViewMode = ViewMode.PROJECTS
    selected_index: int = 0
    scroll_top: int = 0
    filter_query: str = ""
    filter_active: bool = False
    filter_input: str = ""
    detail_open: bool = False
    detail_project: Optional[dict] = None
    show_help: bool = False
    is_scanning: bool = False
    spinner_frame: int = 0
    last_refresh_time: str = ""
    sort_column: str = "cost"  # cost, tokens, sessions, name
    sort_descending: bool = True
    ascii_mode: bool = False
    no_color: bool = False
    meters_expanded: bool = False


SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ASCII_SPINNER = "|/-\\"

SELECTED_ROW_BG = "gray"


def _selected_row_style(state: "TUIState") -> Style:
    if state.no_color:
        return Style(bold=True, inverse=True)
    return Style(bold=True, fg="white", bg=SELECTED_ROW_BG)


def _selected_row_bg(state: "TUIState") -> Optional[str]:
    return None if state.no_color else SELECTED_ROW_BG


def _on_selected_row(state: "TUIState", is_sel: bool, style: Style) -> Style:
    if not is_sel:
        return style
    if state.no_color:
        return Style(bold=style.bold, dim=style.dim, inverse=True,
                     underline=style.underline)
    return Style(fg=style.fg, bg=SELECTED_ROW_BG, bold=style.bold,
                 dim=style.dim, underline=style.underline)


def _active_tab_style(state: "TUIState") -> Style:
    if state.no_color:
        return Style(bold=True, inverse=True)
    return Style(bold=True, fg="black", bg="cyan")


def _table_header_style(state: "TUIState") -> Style:
    if state.no_color:
        return Style(bold=True, inverse=True)
    return Style(bold=True, fg="black", bg="white")


def _fkey_name_style(state: "TUIState") -> Style:
    if state.no_color:
        return Style(inverse=True)
    return Style(fg="black", bg="cyan")


def _filter_prompt_style(state: "TUIState") -> Style:
    if state.no_color:
        return Style(bold=True, inverse=True)
    return Style(bold=True, fg="white", bg="blue")


def _agent_dot_style(agent: str, state: "TUIState", is_sel: bool) -> Style:
    if state.no_color:
        return _selected_row_style(state) if is_sel else Style(bold=True)
    return Style(
        fg=agent_color(agent),
        bg=_selected_row_bg(state) if is_sel else None,
        bold=True,
    )


def _heat_cell_style(dom_ag: Optional[str], state: "TUIState", is_sel: bool) -> Style:
    if state.no_color:
        return _selected_row_style(state) if is_sel else Style(bold=bool(dom_ag))
    return Style(
        fg=agent_color(dom_ag) if dom_ag else None,
        bg=_selected_row_bg(state) if is_sel else None,
        bold=bool(dom_ag),
    )


def _is_weekly_window(w: QuotaMeterWindow) -> bool:
    name = (w.name or "").lower()
    return name.startswith("weekly") or name == "168-hour" or "week" in name


def _weekly_windows(m: SubscriptionMeter) -> List[QuotaMeterWindow]:
    if m.windows and _is_weekly_window(m.windows[0]):
        return [m.windows[0]]
    return []


def _meter_mode_windows(m: SubscriptionMeter, mode: str) -> List[QuotaMeterWindow]:
    if mode == "weekly":
        return _weekly_windows(m)
    return m.windows


def _meter_layout_lines(meters: List[SubscriptionMeter], mode: str, two_col: bool) -> int:
    if not meters or mode == "hidden":
        return 0
    if mode == "compact":
        return len(meters)
    if mode == "quota":
        with_quota = [m for m in meters if m.windows]
        return len(with_quota) + (1 if len(with_quota) < len(meters) else 0)
    blocks = [1 + len(_meter_mode_windows(m, mode)) for m in meters]
    if two_col and len(blocks) > 1:
        split = (len(blocks) + 1) // 2
        return max(sum(blocks[:split]), sum(blocks[split:]))
    return sum(blocks)


def _choose_meter_mode(meters: List[SubscriptionMeter], budget: int,
                       two_col: bool, expanded: bool) -> str:
    if not meters:
        return "hidden"
    if expanded:
        return "full"
    for mode in ("full", "weekly", "compact", "quota"):
        if _meter_layout_lines(meters, mode, two_col) <= budget:
            return mode
    return "hidden"


def _mini_bar(w: QuotaMeterWindow, ascii_mode: bool, length: int = 4) -> str:
    if w.percent is None:
        return ""
    filled = int(round((min(100.0, max(0.0, w.percent)) / 100.0) * length))
    fill = "=" if ascii_mode else "█"
    left = "[" if ascii_mode else "▕"
    right = "]" if ascii_mode else "▏"
    return f"{left}{fill * filled}{' ' * (length - filled)}{right}{int(round(w.percent))}%"


def _compact_meter_body(m: SubscriptionMeter, ascii_mode: bool) -> str:
    parts = [m.plan_label]
    weekly = next((w for w in m.windows if _is_weekly_window(w)), None)
    five = next((w for w in m.windows if not _is_weekly_window(w)
                 and (w.name.lower().startswith("5") or "5h" in w.name.lower())), None)
    if weekly is not None:
        bar = _mini_bar(weekly, ascii_mode)
        parts.append("W " + bar if bar else "W")
    if five is not None and five.percent is not None:
        parts.append(f"5h {int(round(five.percent))}%")
    parts.append(m.multiplier_str)
    usage = m.usage_str
    if usage.startswith("usage "):
        usage = usage[len("usage "):]
    parts.append(usage)
    return "  ".join(parts)


def _meter_label_width(meters: List[SubscriptionMeter], mode: str) -> int:
    longest = 1
    for m in meters:
        for w in _meter_mode_windows(m, mode):
            longest = max(longest, str_width(w.name))
    return max(1, min(16, longest))


def _draw_full_meter_block(canvas: Canvas, x: int, y: int, width: int,
                           m: SubscriptionMeter, windows: List[QuotaMeterWindow],
                           state: "TUIState", label_w: int) -> int:
    dot = "*" if state.ascii_mode else "●"
    canvas.draw_text(x, y, f"{dot} ", Style(fg=m.color, bold=True))
    header = f"{m.plan_label}  {m.price_str}   {m.usage_str}  {m.multiplier_str}"
    header_w = max(0, width - 2)
    canvas.draw_text(x + 2, y, truncate_str(header, header_w), Style(bold=True),
                     max_width=header_w)
    y += 1

    label_x = x + 2
    bar_x = label_x + label_w + 1
    right = x + width
    detail_reserve = 16 if any(w.detail for w in windows) else 0
    bar_len = min(28, max(6, right - bar_x - 8 - detail_reserve))

    for w in windows:
        label = pad_str(truncate_str(w.name, label_w), label_w)
        canvas.draw_text(label_x, y, label, Style(dim=True))

        canvas.draw_text(bar_x, y, "[", Style(dim=True))
        filled = 0
        if w.percent is not None:
            filled = int(round((min(100.0, max(0.0, w.percent)) / 100.0) * bar_len))
        empty = bar_len - filled

        bar_fg = m.color
        if w.level == QuotaLevel.CRITICAL:
            bar_fg = (235, 60, 60)
        elif w.level == QuotaLevel.WARNING:
            bar_fg = (235, 180, 50)

        canvas.draw_text(bar_x + 1, y, "|" * filled, Style(fg=bar_fg, bold=True))
        canvas.draw_text(bar_x + 1 + filled, y, " " * empty, Style())
        canvas.draw_text(bar_x + 1 + bar_len, y, "]", Style(dim=True))

        pct_str = f"{int(round(w.percent)):2d}%" if w.percent is not None else " — "
        pct_style = Style(fg=bar_fg, bold=True) if w.percent is not None else Style(dim=True)
        pct_x = bar_x + bar_len + 3
        canvas.draw_text(pct_x, y, pct_str, pct_style, max_width=max(0, right - pct_x))

        detail_x = pct_x + 5
        if w.detail and detail_x < right:
            canvas.draw_text(detail_x, y, truncate_str(w.detail, right - detail_x),
                             Style(dim=True), max_width=max(0, right - detail_x))
        y += 1
    return len(windows) + 1


def _draw_compact_meters(canvas: Canvas, y: int, meters: List[SubscriptionMeter],
                         width: int, state: "TUIState", add_more: int = 0) -> int:
    dot = "*" if state.ascii_mode else "●"
    for m in meters:
        canvas.draw_text(0, y, f"{dot} ", Style(fg=m.color, bold=True))
        body = _compact_meter_body(m, state.ascii_mode)
        canvas.draw_text(2, y, truncate_str(body, max(0, width - 2)), Style())
        y += 1
    if add_more:
        canvas.draw_text(0, y, f"+{add_more} more", Style(dim=True), max_width=width)
        y += 1
    return y


def render_ui(
    canvas: Canvas,
    state: TUIState,
    filtered: Optional[FilteredData] = None,
    total_vm: Optional[TotalViewModel] = None,
    meters: Optional[List[SubscriptionMeter]] = None,
    accounts_section: Optional[AntigravityAccountsSection] = None,
    project_rows: Optional[List[ProjectRowViewModel]] = None,
    project_footers: Optional[List[ProjectRowViewModel]] = None,
    model_rows: Optional[List[ModelRowViewModel]] = None,
    agent_rows: Optional[List[AgentRowViewModel]] = None,
    day_rows: Optional[List[DayRowViewModel]] = None,
    detail_vm: Optional[ProjectDetailViewModel] = None,
    static_mode: bool = False,
) -> None:
    """Render the full TUI layout onto canvas."""
    width = canvas.width
    height = canvas.height

    # 1. Terminal too small check (< 60 cols or < 15 rows)
    if width < 60 or height < 15:
        msg = f"Terminal too small (need >= 60x15, current: {width}x{height})"
        canvas.draw_text(0, 0, msg[:width], Style(bold=True, fg="yellow"))
        return

    if filtered is None:
        # Immediate Loading screen
        ver_str = f"Kanjo {state.version}"
        cur_x = canvas.draw_text(0, 0, ver_str, Style(bold=True, fg="cyan"))
        cur_x = canvas.draw_text(cur_x, 0, " · ", Style(dim=True))

        for idx, (r_val, r_label) in enumerate(RANGE_TABS):
            is_active = (state.time_range == r_val)
            tab_str = f" {r_label} "
            tab_style = _active_tab_style(state) if is_active else Style()
            cur_x = canvas.draw_text(cur_x, 0, tab_str, tab_style)
            if idx < len(RANGE_TABS) - 1:
                cur_x = canvas.draw_text(cur_x, 0, " ", Style())

        spin = ASCII_SPINNER[state.spinner_frame % len(ASCII_SPINNER)] if state.ascii_mode else SPINNER_CHARS[state.spinner_frame % len(SPINNER_CHARS)]
        right_str = f"{spin} Loading…"
        rw = str_width(right_str)
        if width - rw > cur_x + 1:
            canvas.draw_text(width - rw, 0, right_str, Style(fg="yellow"))

        load_msg = "Loading…"
        ly = height // 2
        lx = max(0, (width - str_width(load_msg)) // 2)
        canvas.draw_text(lx, ly, load_msg, Style(bold=True, fg="cyan"))

        bar_y = height - 1
        canvas.fill_rect(0, bar_y, width, 1, " ", Style())
        bx = 0
        for key_lbl, name_lbl in [("F1", "Help"), ("F10", "Quit")]:
            if bx >= width:
                break
            k_style = Style(bold=True)
            bx = canvas.draw_text(bx, bar_y, f"{key_lbl}", k_style)
            n_style = _fkey_name_style(state)
            bx = canvas.draw_text(bx, bar_y, f"{name_lbl} ", n_style)
        return

    meters = meters or []
    project_rows = project_rows or []
    project_footers = project_footers or []
    model_rows = model_rows or []
    agent_rows = agent_rows or []
    day_rows = day_rows or []

    cur_y = 0

    # 2. Header Line (y=0)
    # Kanjo <version> · range tabs All Today 7d 30d Since reset Cycle · last refresh time · spinner
    ver_str = f"Kanjo {state.version}"
    cur_x = canvas.draw_text(0, cur_y, ver_str, Style(bold=True, fg="cyan"))
    cur_x = canvas.draw_text(cur_x, cur_y, " · ", Style(dim=True))

    # Range tabs
    for idx, (r_val, r_label) in enumerate(RANGE_TABS):
        is_active = (state.time_range == r_val)
        tab_str = f" {r_label} "
        if is_active:
            tab_style = _active_tab_style(state)
        else:
            tab_style = Style()
        cur_x = canvas.draw_text(cur_x, cur_y, tab_str, tab_style)
        if idx < len(RANGE_TABS) - 1:
            cur_x = canvas.draw_text(cur_x, cur_y, " ", Style())

    # Right side: refresh time and spinner
    right_items = []
    if state.is_scanning:
        spin = ASCII_SPINNER[state.spinner_frame % len(ASCII_SPINNER)] if state.ascii_mode else SPINNER_CHARS[state.spinner_frame % len(SPINNER_CHARS)]
        right_items.append(f"{spin} refreshing…")
    if state.last_refresh_time:
        right_items.append(state.last_refresh_time)

    right_str = " · ".join(right_items)
    if right_str:
        rw = str_width(right_str)
        rx = width - rw
        if rx > cur_x + 1:
            canvas.draw_text(rx, cur_y, right_str, Style(fg="yellow" if state.is_scanning else "gray"))

    cur_y += 1

    # 3. Total Line
    # $275.99 · 266.2M tokens · 150 sessions · 8 projects
    total_line = f"{total_vm.cost_str}  ·  {total_vm.tokens_str}  ·  {total_vm.sessions_str}  ·  {total_vm.projects_str}"
    canvas.draw_text(0, cur_y, total_line, Style(bold=True, fg="white"))
    cur_y += 1

    # Agent Share Bar & Legend
    # e.g. [██████████████████████████████████████████████████████████]
    # ■ Claude Code 65% ■ Codex CLI 25%
    bar_width = min(36, max(16, width - 40))
    canvas.draw_text(0, cur_y, "[", Style(dim=True))
    bx = 1
    total_pct_drawn = 0
    if total_vm.shares:
        for idx, (ag, lbl, cost, pct, rgb) in enumerate(total_vm.shares):
            seg_w = int(round((pct / 100.0) * bar_width))
            if idx == len(total_vm.shares) - 1:
                seg_w = bar_width - bx + 1
            if seg_w > 0 and bx - 1 + seg_w <= bar_width:
                block_ch = "=" if state.ascii_mode else "█"
                canvas.draw_text(bx, cur_y, block_ch * seg_w, Style(fg=rgb))
                bx += seg_w
    rem_bar = (1 + bar_width) - bx
    if rem_bar > 0:
        canvas.draw_text(bx, cur_y, " " * rem_bar, Style())
        bx += rem_bar
    canvas.draw_text(1 + bar_width, cur_y, "]", Style(dim=True))

    # Legend: drop whole items that do not fit, then summarise with +N.
    leg_x = bar_width + 4
    dot = "*" if state.ascii_mode else "■"
    legend_items = [
        (f" {dot} {lbl} {pct:.0f}%", lbl, pct, rgb)
        for ag, lbl, cost, pct, rgb in total_vm.shares
    ]
    dropped = 0
    while legend_items:
        total_w = sum(str_width(it[0]) for it in legend_items)
        suffix_w = str_width(f" +{dropped}") if dropped else 0
        if leg_x + total_w + suffix_w <= width:
            break
        legend_items.pop()
        dropped += 1
    for item_text, lbl, pct, rgb in legend_items:
        leg_x = canvas.draw_text(leg_x, cur_y, f" {dot} ", Style(fg=rgb))
        leg_x = canvas.draw_text(leg_x, cur_y, f"{lbl} {pct:.0f}%", Style(dim=True))
    if dropped:
        canvas.draw_text(leg_x, cur_y, f" +{dropped}", Style(dim=True),
                         max_width=max(0, width - leg_x))

    cur_y += 1

    # Bottom reserved rows: 1 row for F-key bar, plus 1 if filter prompt active
    bottom_reserved = 2 if state.filter_active else 1
    table_bottom_y = height - bottom_reserved

    # Like htop, keep a meaningful slice of the screen for the table.
    if height >= 24:
        table_min = max(8, int(math.ceil(height * 0.4)))
    else:
        table_min = max(2, min(4, height - 4))
    if state.meters_expanded:
        table_min = 1
    content_limit_y = table_bottom_y - table_min - 1

    # 4. Subscriptions / Quota Meters (htop CPU-meter style)
    two_col = width >= 110 and len(meters) > 1
    meter_budget = max(0, content_limit_y - cur_y)
    meter_mode = _choose_meter_mode(meters, meter_budget, two_col, state.meters_expanded)

    if meter_mode in ("full", "weekly"):
        label_w = _meter_label_width(meters, meter_mode)
        if two_col:
            split = (len(meters) + 1) // 2
            cols = [meters[:split], meters[split:]]
            col_w = (width - 2) // 2
            max_col_y = cur_y
            for ci, col in enumerate(cols):
                col_x = ci * (col_w + 2)
                col_y = cur_y
                for m in col:
                    if col_y >= content_limit_y:
                        break
                    col_y += _draw_full_meter_block(
                        canvas, col_x, col_y, col_w, m,
                        _meter_mode_windows(m, meter_mode), state, label_w
                    )
                max_col_y = max(max_col_y, col_y)
            cur_y = max_col_y
        else:
            for m in meters:
                if cur_y >= content_limit_y:
                    break
                cur_y += _draw_full_meter_block(
                    canvas, 0, cur_y, width, m,
                    _meter_mode_windows(m, meter_mode), state, label_w
                )
    elif meter_mode == "compact":
        cur_y = _draw_compact_meters(canvas, cur_y, meters, width, state, 0)
    elif meter_mode == "quota":
        with_quota = [m for m in meters if m.windows]
        dropped_meters = len(meters) - len(with_quota)
        cur_y = _draw_compact_meters(canvas, cur_y, with_quota, width, state, dropped_meters)

    # 5. Antigravity Accounts (only if attribution data exists)
    if accounts_section and cur_y < content_limit_y:
        remaining = content_limit_y - cur_y
        if remaining >= 2:
            # Header
            canvas.draw_text(0, cur_y, accounts_section.header_label, Style(bold=True, fg="white"))
            cur_y += 1
            for r in accounts_section.rows:
                if cur_y >= content_limit_y:
                    break
                acc_col_w = min(36, max(20, width - 40))
                email_str = pad_str(truncate_str(r.email, acc_col_w), acc_col_w)
                tok_str = pad_str(r.tokens_str, 8, align="right")
                cost_str = pad_str(r.cost_str, 10, align="right")
                cur_marker = ""
                cur_style = Style()
                if r.is_current:
                    cur_marker = "  * current" if state.ascii_mode else "  ● current"
                    cur_style = Style(fg="green", bold=True)

                row_style = Style(dim=True) if r.is_unattributed else Style()
                canvas.draw_text(2, cur_y, email_str, row_style)
                canvas.draw_text(2 + acc_col_w + 2, cur_y, tok_str, row_style)
                canvas.draw_text(2 + acc_col_w + 12, cur_y, cost_str, row_style)
                if cur_marker:
                    canvas.draw_text(2 + acc_col_w + 22, cur_y, cur_marker, cur_style)
                cur_y += 1

    # Separator line before main table if space permits
    if cur_y < table_bottom_y - 2:
        canvas.draw_hline(0, cur_y, width, "─" if not state.ascii_mode else "-", Style(dim=True))
        cur_y += 1

    # 6. Main Table
    # Determine table columns based on view_mode
    table_header_y = cur_y
    header_style = _table_header_style(state)

    if state.view_mode == ViewMode.PROJECTS:
        # Columns: PROJECT, COST, TOKENS, SESSIONS, AGENTS, LAST ACTIVE, 8W
        # Fix column widths:
        # COST: 10, TOKENS: 8, SESSIONS: 8, AGENTS: 8, LAST ACTIVE: 11, 8W: 8
        fixed_w = 10 + 8 + 8 + 8 + 11 + 8 + 6  # 59
        proj_w = max(16, width - fixed_w)

        h_proj = pad_str("PROJECT", proj_w)
        h_cost = pad_str("COST", 10, align="right")
        h_tok = pad_str("TOKENS", 8, align="right")
        h_sess = pad_str("SESSIONS", 8, align="right")
        h_ag = pad_str("AGENTS", 8, align="center")
        h_last = pad_str("LAST ACTIVE", 11, align="right")
        h_8w = pad_str("8W", 8, align="center")

        h_line = f"{h_proj} {h_cost} {h_tok} {h_sess} {h_ag} {h_last} {h_8w}"
        canvas.fill_rect(0, table_header_y, width, 1, " ", header_style)
        canvas.draw_text(0, table_header_y, h_line[:width], header_style)
        cur_y += 1

        # Visible rows
        visible_height = max(0, table_bottom_y - cur_y)
        footer_height = min(len(project_footers), visible_height)
        body_height = max(0, visible_height - footer_height)

        # In static mode, show top 15 projects bounded by body_height
        if static_mode:
            shown_projects = project_rows[:min(15, body_height)]
            scroll_offset = 0
        else:
            total_items = len(project_rows)
            # Ensure selected_index is within bounds
            if total_items > 0:
                state.selected_index = max(0, min(total_items - 1, state.selected_index))
            else:
                state.selected_index = 0

            # Scroll view
            if body_height > 0:
                if state.selected_index < state.scroll_top:
                    state.scroll_top = state.selected_index
                elif state.selected_index >= state.scroll_top + body_height:
                    state.scroll_top = state.selected_index - body_height + 1
            else:
                state.scroll_top = 0

            scroll_offset = state.scroll_top
            shown_projects = project_rows[scroll_offset:scroll_offset + body_height] if body_height > 0 else []

        for idx, row in enumerate(shown_projects):
            row_y = cur_y + idx
            is_sel = (scroll_offset + idx == state.selected_index)
            row_style = _selected_row_style(state) if is_sel else Style()

            if is_sel:
                canvas.fill_rect(0, row_y, width, 1, " ", row_style)

            # Project name
            p_name = pad_str(truncate_str(row.name, proj_w), proj_w)
            canvas.draw_text(0, row_y, p_name, row_style)
            rx = proj_w + 1

            # Cost
            c_str = pad_str(row.cost_str, 10, align="right")
            canvas.draw_text(rx, row_y, c_str, row_style)
            rx += 11

            # Tokens
            t_str = pad_str(row.tokens_str, 8, align="right")
            canvas.draw_text(rx, row_y, t_str, row_style)
            rx += 9

            # Sessions
            s_str = pad_str(row.sessions_str, 8, align="right")
            canvas.draw_text(rx, row_y, s_str, row_style)
            rx += 9

            # Agents dots
            dot_x = rx
            for ag in row.agents[:6]:
                dot_ch = "*" if state.ascii_mode else "●"
                dot_style = _agent_dot_style(ag, state, is_sel)
                canvas.draw_text(dot_x, row_y, dot_ch, dot_style)
                dot_x += 1
            rx += 9

            # Last Active
            l_str = pad_str(row.last_active_str, 11, align="right")
            canvas.draw_text(rx, row_y, l_str, row_style)
            rx += 12

            # 8W Heat Strip
            for ch, dom_ag in row.heat_strip:
                h_style = _heat_cell_style(dom_ag, state, is_sel)
                canvas.draw_text(rx, row_y, ch, h_style)
                rx += 1

        cur_y += len(shown_projects)

        # Footer rows
        if cur_y < table_bottom_y:
            canvas.draw_hline(0, cur_y, width, "─" if not state.ascii_mode else "-", Style(dim=True))
            cur_y += 1
            for f_row in project_footers:
                if cur_y >= table_bottom_y:
                    break
                f_style = Style(bold=True) if f_row.is_total else Style(dim=True)
                p_name = pad_str(truncate_str(f_row.name, proj_w), proj_w)
                canvas.draw_text(0, cur_y, p_name, f_style)
                rx = proj_w + 1

                c_str = pad_str(f_row.cost_str, 10, align="right")
                canvas.draw_text(rx, cur_y, c_str, f_style)
                rx += 11

                t_str = pad_str(f_row.tokens_str, 8, align="right")
                canvas.draw_text(rx, cur_y, t_str, f_style)
                rx += 9

                s_str = pad_str(f_row.sessions_str, 8, align="right")
                canvas.draw_text(rx, cur_y, s_str, f_style)
                rx += 9

                # Blank agents
                rx += 9

                l_str = pad_str(f_row.last_active_str, 11, align="right")
                canvas.draw_text(rx, cur_y, l_str, f_style)
                cur_y += 1

    elif state.view_mode == ViewMode.MODELS:
        # Columns: MODEL, PROVIDER, TOKENS, COST
        mod_w = max(20, width - 40)
        h_mod = pad_str("MODEL", mod_w)
        h_prov = pad_str("PROVIDER", 15)
        h_tok = pad_str("TOKENS", 10, align="right")
        h_cost = pad_str("COST", 10, align="right")
        h_line = f"{h_mod} {h_prov} {h_tok} {h_cost}"
        canvas.fill_rect(0, table_header_y, width, 1, " ", header_style)
        canvas.draw_text(0, table_header_y, h_line[:width], header_style)
        cur_y += 1

        body_height = max(0, table_bottom_y - cur_y)
        total_items = len(model_rows)
        if total_items > 0:
            state.selected_index = max(0, min(total_items - 1, state.selected_index))
        else:
            state.selected_index = 0

        if body_height > 0:
            if state.selected_index < state.scroll_top:
                state.scroll_top = state.selected_index
            elif state.selected_index >= state.scroll_top + body_height:
                state.scroll_top = state.selected_index - body_height + 1
        else:
            state.scroll_top = 0

        scroll_offset = state.scroll_top
        shown_models = model_rows[scroll_offset:scroll_offset + body_height] if not static_mode else model_rows[:min(15, body_height)]

        for idx, row in enumerate(shown_models):
            row_y = cur_y + idx
            is_sel = (scroll_offset + idx == state.selected_index)
            row_style = _selected_row_style(state) if is_sel else Style()
            if is_sel:
                canvas.fill_rect(0, row_y, width, 1, " ", row_style)

            canvas.draw_text(0, row_y, pad_str(truncate_str(row.model, mod_w), mod_w), row_style)
            rx = mod_w + 1
            canvas.draw_text(rx, row_y, pad_str(truncate_str(row.provider, 15), 15), row_style)
            rx += 16
            canvas.draw_text(rx, row_y, pad_str(row.tokens_str, 10, align="right"), row_style)
            rx += 11
            canvas.draw_text(rx, row_y, pad_str(row.cost_str, 10, align="right"), row_style)

    elif state.view_mode == ViewMode.AGENTS:
        # Columns: AGENT, SESSIONS, TOKENS, COST, SHARE
        ag_w = max(16, width - 50)
        h_ag = pad_str("AGENT", ag_w)
        h_sess = pad_str("SESSIONS", 10, align="right")
        h_tok = pad_str("TOKENS", 10, align="right")
        h_cost = pad_str("COST", 10, align="right")
        h_share = "SHARE"
        h_line = f"{h_ag} {h_sess} {h_tok} {h_cost}  {h_share}"
        canvas.fill_rect(0, table_header_y, width, 1, " ", header_style)
        canvas.draw_text(0, table_header_y, h_line[:width], header_style)
        cur_y += 1

        body_height = max(0, table_bottom_y - cur_y)
        total_items = len(agent_rows)
        if total_items > 0:
            state.selected_index = max(0, min(total_items - 1, state.selected_index))
        else:
            state.selected_index = 0

        if body_height > 0:
            if state.selected_index < state.scroll_top:
                state.scroll_top = state.selected_index
            elif state.selected_index >= state.scroll_top + body_height:
                state.scroll_top = state.selected_index - body_height + 1
        else:
            state.scroll_top = 0

        scroll_offset = state.scroll_top
        shown_agents = agent_rows[scroll_offset:scroll_offset + body_height] if not static_mode else agent_rows[:min(15, body_height)]

        for idx, row in enumerate(shown_agents):
            row_y = cur_y + idx
            is_sel = (scroll_offset + idx == state.selected_index)
            row_style = _selected_row_style(state) if is_sel else Style()
            if is_sel:
                canvas.fill_rect(0, row_y, width, 1, " ", row_style)

            canvas.draw_text(0, row_y, pad_str(truncate_str(row.label, ag_w), ag_w), row_style)
            rx = ag_w + 1
            canvas.draw_text(rx, row_y, pad_str(row.sessions_str, 10, align="right"), row_style)
            rx += 11
            canvas.draw_text(rx, row_y, pad_str(row.tokens_str, 10, align="right"), row_style)
            rx += 11
            canvas.draw_text(rx, row_y, pad_str(row.cost_str, 10, align="right"), row_style)
            rx += 12

            # Share bar [████░░░░] 45.2%
            bar_len = min(16, max(8, width - rx - 10))
            if bar_len > 0:
                filled = int(round((row.share_pct / 100.0) * bar_len))
                empty = bar_len - filled
                canvas.draw_text(rx, row_y, "[", _on_selected_row(state, is_sel, Style(dim=True)))
                block_ch = "=" if state.ascii_mode else "█"
                canvas.draw_text(rx + 1, row_y, block_ch * filled,
                                 _on_selected_row(state, is_sel, Style(fg=row.color, bold=True)))
                canvas.draw_text(rx + 1 + filled, row_y, " " * empty,
                                 _on_selected_row(state, is_sel, Style()))
                canvas.draw_text(rx + 1 + bar_len, row_y, "]",
                                 _on_selected_row(state, is_sel, Style(dim=True)))
                canvas.draw_text(rx + 3 + bar_len, row_y, f"{row.share_pct:5.1f}%", row_style)

    elif state.view_mode == ViewMode.DAYS:
        # Columns: DATE, COST BAR, COST, TOKENS
        h_date = pad_str("DATE", 12)
        h_cost = pad_str("COST", 10, align="right")
        h_tok = pad_str("TOKENS", 10, align="right")
        bar_len = min(30, max(10, width - 40))
        h_bar = pad_str("COST BAR", bar_len + 2)
        h_line = f"{h_date} {h_bar} {h_cost} {h_tok}"
        canvas.fill_rect(0, table_header_y, width, 1, " ", header_style)
        canvas.draw_text(0, table_header_y, h_line[:width], header_style)
        cur_y += 1

        body_height = max(0, table_bottom_y - cur_y)
        total_items = len(day_rows)
        if total_items > 0:
            state.selected_index = max(0, min(total_items - 1, state.selected_index))
        else:
            state.selected_index = 0

        if body_height > 0:
            if state.selected_index < state.scroll_top:
                state.scroll_top = state.selected_index
            elif state.selected_index >= state.scroll_top + body_height:
                state.scroll_top = state.selected_index - body_height + 1
        else:
            state.scroll_top = 0

        scroll_offset = state.scroll_top
        shown_days = day_rows[scroll_offset:scroll_offset + body_height] if not static_mode else day_rows[:min(15, body_height)]

        for idx, row in enumerate(shown_days):
            row_y = cur_y + idx
            is_sel = (scroll_offset + idx == state.selected_index)
            row_style = _selected_row_style(state) if is_sel else Style()
            if is_sel:
                canvas.fill_rect(0, row_y, width, 1, " ", row_style)

            canvas.draw_text(0, row_y, pad_str(row.date_str, 12), row_style)
            rx = 13

            # Bar
            filled = int(round(row.cost_ratio * bar_len))
            empty = bar_len - filled
            canvas.draw_text(rx, row_y, "[", _on_selected_row(state, is_sel, Style(dim=True)))
            block_ch = "=" if state.ascii_mode else "█"
            canvas.draw_text(rx + 1, row_y, block_ch * filled,
                             _on_selected_row(state, is_sel, Style(fg="cyan", bold=True)))
            canvas.draw_text(rx + 1 + filled, row_y, " " * empty,
                             _on_selected_row(state, is_sel, Style()))
            canvas.draw_text(rx + 1 + bar_len, row_y, "]",
                             _on_selected_row(state, is_sel, Style(dim=True)))
            rx += bar_len + 3

            canvas.draw_text(rx, row_y, pad_str(row.cost_str, 10, align="right"), row_style)
            rx += 11
            canvas.draw_text(rx, row_y, pad_str(row.tokens_str, 10, align="right"), row_style)

    # 7. Filter input bar (if active)
    if state.filter_active:
        fy = height - 2
        f_prompt = f"Filter: {state.filter_input}_ (Enter to apply, Esc to cancel)"
        filter_style = _filter_prompt_style(state)
        canvas.fill_rect(0, fy, width, 1, " ", filter_style)
        canvas.draw_text(1, fy, f_prompt[:width - 2], filter_style)

    # 8. F-key Bar (last line, y = height - 1)
    # F1Help F2Range F3View F4Filter F5Refresh F6Sort F10Quit
    bar_y = height - 1
    f_items = [
        ("F1", "Help"),
        ("F2", "Range"),
        ("F3", "View"),
        ("F4", "Filter"),
        ("F5", "Refresh"),
        ("F6", "Sort"),
        ("F7", "Meters"),
        ("F10", "Quit"),
    ]
    canvas.fill_rect(0, bar_y, width, 1, " ", Style())
    bx = 0
    for key_lbl, name_lbl in f_items:
        if bx >= width:
            break
        k_style = Style(bold=True)
        bx = canvas.draw_text(bx, bar_y, f"{key_lbl}", k_style)
        n_style = _fkey_name_style(state)
        bx = canvas.draw_text(bx, bar_y, f"{name_lbl} ", n_style)

    # 9. Detail Pane Overlay
    if state.detail_open and detail_vm is not None:
        dw = min(width - 4, 80)
        dh = min(height - 4, 22)
        dx = (width - dw) // 2
        dy = (height - dh) // 2

        canvas.draw_box(dx, dy, dw, dh, title=f"Project: {detail_vm.name}",
                        style=Style(bg="black", fg="white"),
                        border_style=Style(fg="cyan", bold=True),
                        ascii_mode=state.ascii_mode)

        cy = dy + 1
        if detail_vm.remote:
            canvas.draw_text(dx + 2, cy, f"Remote: {detail_vm.remote}", Style(fg="gray"), max_width=dw - 4)
            cy += 1
        if detail_vm.paths:
            p_str = ", ".join(detail_vm.paths)
            canvas.draw_text(dx + 2, cy, f"Paths:  {p_str}", Style(fg="gray"), max_width=dw - 4)
            cy += 1

        stats_line = f"Cost: {detail_vm.cost_str}  ·  Tokens: {detail_vm.tokens_str}  ·  Sessions: {detail_vm.sessions_str}"
        canvas.draw_text(dx + 2, cy, stats_line, Style(bold=True), max_width=dw - 4)
        cy += 1

        spark_line = f"30-day sparkline: {detail_vm.sparkline_30d}  ({detail_vm.sparkline_peak_str})"
        canvas.draw_text(dx + 2, cy, spark_line, Style(fg="cyan"), max_width=dw - 4)
        cy += 1

        # Divider
        canvas.draw_hline(dx + 1, cy, dw - 2, "─" if not state.ascii_mode else "-", Style(dim=True))
        cy += 1

        # By Agent
        canvas.draw_text(dx + 2, cy, "By Agent:", Style(bold=True))
        cy += 1
        for lbl, c, t, s, pct, rgb in detail_vm.by_agent[:4]:
            if cy >= dy + dh - 7:
                break
            dot = "*" if state.ascii_mode else "●"
            ag_line = f"  {dot} {pad_str(lbl, 16)}  {pad_str(c, 10, align='right')}  {pad_str(t, 8, align='right')}  {pad_str(s, 4, align='right')}  ({pct:.1f}%)"
            canvas.draw_text(dx + 2, cy, f"  {dot} ", Style(fg=rgb, bold=True))
            canvas.draw_text(dx + 6, cy, ag_line[4:], Style())
            cy += 1

        # Divider
        canvas.draw_hline(dx + 1, cy, dw - 2, "─" if not state.ascii_mode else "-", Style(dim=True))
        cy += 1

        # By Model
        canvas.draw_text(dx + 2, cy, "By Model:", Style(bold=True))
        cy += 1
        for m_name, prov, c, t in detail_vm.by_model[:4]:
            if cy >= dy + dh - 3:
                break
            m_line = f"  {pad_str(truncate_str(m_name, 22), 22)}  {pad_str(prov, 12)}  {pad_str(c, 10, align='right')}  {pad_str(t, 8, align='right')}"
            canvas.draw_text(dx + 2, cy, m_line, Style())
            cy += 1

        # Close note at bottom of detail pane
        close_note = "[Esc / Backspace] Close"
        canvas.draw_text(dx + (dw - len(close_note)) // 2, dy + dh - 2, close_note, Style(dim=True))

    # 10. Help Overlay
    if state.show_help:
        hw = max(24, min(width - 4, 76))
        hx = (width - hw) // 2
        title_col_w = 12
        desc_x_off = 2 + title_col_w + 2
        desc_w = max(8, hw - desc_x_off - 2)

        help_lines = [
            ("Navigation", "↑ / ↓ / PgUp / PgDn / Home / End to scroll rows"),
            ("Time Range", "1-6 or ← / → to change range (All, Today, 7d, 30d, Reset, Cycle)"),
            ("Views", "Tab / F3 or p / m / a / d to switch view (Projects, Models, Agents, Days)"),
            ("Detail", "Enter on a project to open details, Esc / Backspace to close"),
            ("Filter", "/ or F4 to filter by name, Enter to confirm, Esc to cancel"),
            ("Sort", "s or F6 to cycle sort column"),
            ("Meters", "M or F7 toggles expanded meters (full quota detail, smaller table)"),
            ("Refresh", "r or F5 to refresh now (in-process re-scan)"),
            ("Quit", "q or F10 to exit cleanly"),
        ]

        wrapped = []
        for title_str, desc in help_lines:
            rows = textwrap.wrap(desc, width=desc_w, break_long_words=True,
                                 break_on_hyphens=False) or [""]
            wrapped.append((title_str, rows))

        needed = 2 + sum(len(rows) for _, rows in wrapped) + 2
        hh = max(8, min(height - 4, needed))
        hy = (height - hh) // 2

        # Clear the full rows behind the overlay so no text bleeds around the box.
        canvas.fill_rect(0, hy, width, hh, " ", Style())

        canvas.draw_box(hx, hy, hw, hh, title="Help & Shortcuts",
                        style=Style(bg="black", fg="white"),
                        border_style=Style(fg="yellow", bold=True),
                        ascii_mode=state.ascii_mode)

        cy = hy + 2
        last_cy = hy + hh - 3
        for title_str, rows in wrapped:
            if cy > last_cy:
                break
            canvas.draw_text(hx + 2, cy, pad_str(title_str, title_col_w),
                             Style(bold=True, fg="cyan"), max_width=title_col_w)
            for i, row in enumerate(rows):
                if cy > last_cy:
                    break
                canvas.draw_text(hx + desc_x_off, cy, row, Style(), max_width=desc_w)
                cy += 1

        close_note = "Press any key to close help"
        note_x = hx + max(1, (hw - str_width(close_note)) // 2)
        canvas.draw_text(note_x, hy + hh - 2, truncate_str(close_note, hw - 2),
                         Style(dim=True), max_width=max(0, hx + hw - 1 - note_x))
