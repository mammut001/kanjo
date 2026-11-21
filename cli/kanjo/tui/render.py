"""Pure Canvas abstraction and view-model rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Any, Dict, List, Optional, Tuple, Union
import unicodedata

from .model import (
    AgentDetailViewModel, AntigravityAccountsSection, AntigravityAccountRow,
    DayRowViewModel, FilteredData, ModelRowViewModel, ProjectDetailViewModel,
    ProjectRowViewModel, QuotaLevel, QuotaMeterWindow, RANGE_TABS,
    SubscriptionMeter, TimeRange, TotalViewModel, VIEW_MODES, ViewMode,
    format_money, format_tokens, agent_color, get_tz, parse_iso_dt
)
from .i18n import t, normalize_lang

# A clickable region recorded by the renderer: ``(y, x0, x1, action)`` with an
# inclusive x range. ``action`` is ``range:<value>``, ``fkey:<name>``,
# ``row:<index>`` or ``sort:<column>``; the terminal layer maps it to the same
# behaviour as the keyboard.
HitBox = Tuple[int, int, int, str]

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


def _is_cjk(ch: str) -> bool:
    """True for characters that may start a new line without a space (CJK/wide)."""
    if not ch:
        return False
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return True
    code = ord(ch)
    return (
        0x3040 <= code <= 0x30FF      # kana
        or 0x3400 <= code <= 0x9FFF   # CJK unified ideographs
        or 0xF900 <= code <= 0xFAFF   # compatibility ideographs
    )


def wrap_display(text: str, width: int) -> List[str]:
    """Wrap text by terminal display width (CJK characters count as 2).

    Latin words are kept intact and break only at whitespace (a word longer
    than the line is broken as a last resort). CJK text may break between any
    two characters.
    """
    if width <= 0:
        return [""]

    # Split into words, single spaces and individual CJK characters.
    tokens: List[str] = []
    buf = ""
    for ch in text:
        if ch == " ":
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(" ")
        elif _is_cjk(ch):
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
        else:
            buf += ch
    if buf:
        tokens.append(buf)

    lines: List[str] = []
    cur = ""
    cur_w = 0
    pending_space = False

    def flush() -> None:
        nonlocal cur, cur_w, pending_space
        lines.append(cur.rstrip())
        cur = ""
        cur_w = 0
        pending_space = False

    for tok in tokens:
        if tok == " ":
            if cur:
                pending_space = True
            continue
        tw = str_width(tok)
        space_w = 1 if (cur and pending_space) else 0
        if cur and cur_w + space_w + tw > width:
            flush()
        if not cur and pending_space:
            pending_space = False
        if tw <= width:
            if cur and pending_space:
                cur += " "
                cur_w += 1
            cur += tok
            cur_w += tw
            pending_space = False
            continue
        # Very long word: break it by display width.
        for ch in tok:
            cw = char_width(ch)
            if cur and cur_w + cw > width:
                flush()
            cur += ch
            cur_w += cw

    if cur or not lines:
        lines.append(cur)
    return lines


def hit_box_at(hit_boxes: List[HitBox], y: int, x: int) -> Optional[str]:
    """Return the action of the region containing ``(y, x)``, if any.

    Later boxes win, so a region drawn on top of another one (an overlay row,
    a re-drawn tab) takes precedence.
    """
    for box_y, x0, x1, action in reversed(hit_boxes):
        if box_y == y and x0 <= x <= x1:
            return action
    return None


def _add_hit_box(hit_boxes: List[HitBox], y: int, x0: int, x1: int, action: str,
                  width: int) -> None:
    """Record a clickable region, clipped to the canvas and never inverted."""
    if y < 0 or x1 < x0:
        return
    hit_boxes.append((y, max(0, x0), min(width - 1, x1), action))


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

    def _clear_wide_at(self, x: int, y: int) -> None:
        if not (0 <= y < self.height and 0 <= x < self.width):
            return
        row = self.grid[y]
        if row[x].char == "" and x > 0:
            row[x - 1] = Cell()
        elif char_width(row[x].char) == 2 and x + 1 < self.width:
            row[x + 1] = Cell()

    def set_cell(self, x: int, y: int, char: str, style: Style = Style()) -> None:
        if 0 <= y < self.height and 0 <= x < self.width:
            self._clear_wide_at(x, y)
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
                self._clear_wide_at(cur_x, y)
                if cw == 2:
                    self._clear_wide_at(cur_x + 1, y)
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
                self.set_cell(cx, cy, char, style)

    def draw_hline(self, x: int, y: int, w: int, char: str = "─",
                   style: Style = Style()) -> None:
        if 0 <= y < self.height:
            cw = char_width(char)
            cur_x = x
            while cur_x < x + w and cur_x + cw <= self.width:
                if cur_x >= 0:
                    self._clear_wide_at(cur_x, y)
                    if cw == 2:
                        self._clear_wide_at(cur_x + 1, y)
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
    detail_agent: Optional[str] = None
    show_help: bool = False
    is_scanning: bool = False
    spinner_frame: int = 0
    last_refresh_time: str = ""
    sort_column: str = "cost"  # cost, tokens, sessions, name
    sort_descending: bool = True
    ascii_mode: bool = False
    no_color: bool = False
    meters_expanded: bool = False
    lang: str = "en"
    confirm_switch_email: Optional[str] = None
    status_message: str = ""
    status_until: float = 0.0
    is_stale: bool = False
    last_generated_at_str: str = ""
    # Error of the last failed refresh while no report has loaded yet.
    load_error: str = ""


SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
ASCII_SPINNER = "|/-\\"

SELECTED_ROW_BG = "gray"
# Background of the project detail overlay (solid over the whole pane).
DETAIL_PANE_BG = "black"


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
    return (name.startswith("weekly") or name == "168-hour" or "week" in name
            or name in ("每周", "周") or name.startswith("每周"))


def _weekly_windows(m: SubscriptionMeter) -> List[QuotaMeterWindow]:
    if m.windows and _is_weekly_window(m.windows[0]):
        return [m.windows[0]]
    placeholders = [w for w in m.windows
                    if w.percent is None and w.level is None and w.detail]
    return placeholders


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


def _compact_meter_body(m: SubscriptionMeter, ascii_mode: bool, lang: str = "en") -> str:
    parts = [m.plan_label]
    weekly = next((w for w in m.windows if _is_weekly_window(w)), None)
    five = next((w for w in m.windows if not _is_weekly_window(w)
                 and (w.name.lower().startswith("5") or "5h" in w.name.lower())), None)
    if weekly is not None:
        bar = _mini_bar(weekly, ascii_mode)
        label = t("meter.weekly_short", lang)
        parts.append(label + " " + bar if bar else label)
    if five is not None and five.percent is not None:
        parts.append(f"{t('meter.five_short', lang)} {int(round(five.percent))}%")
    parts.append(m.multiplier_str)
    usage = m.usage_str
    prefix = t("meter.usage", lang, amount="")
    if prefix and usage.startswith(prefix):
        usage = usage[len(prefix):]
    parts.append(usage)
    if weekly is None and five is None:
        placeholders = [w for w in m.windows if w.percent is None and w.detail]
        if placeholders:
            parts[-1:] = ["—", placeholders[0].detail]
    return "  ".join(parts)


def _meter_label_width(meters: List[SubscriptionMeter], mode: str, col_w: int) -> int:
    """Width of the label column: the longest label shown, capped so the bar
    keeps at least ~10 cells in a column of ``col_w`` cells (the reserve covers
    the ``[ ]``, the percentage and the detail text). Only longer labels are
    truncated, and only when they really do not fit."""
    longest = 1
    for m in meters:
        for w in _meter_mode_windows(m, mode):
            longest = max(longest, str_width(w.name))
    # 2 (indent) + 1 (gap) + 8 (brackets, pct) + 16 (detail) + 10 (bar)
    cap = max(8, col_w - 2 - 1 - 8 - 16 - 10)
    return max(1, min(cap, longest))


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
    right = x + width

    # Subscription with no live quota data: one dim explanatory row, no meter.
    if len(windows) == 1 and windows[0].placeholder:
        w = windows[0]
        label = pad_str(truncate_str(w.name, label_w), label_w)
        canvas.draw_text(label_x, y, label, Style(dim=True))
        text = "—"
        if w.detail:
            text += "  " + w.detail
        canvas.draw_text(label_x + label_w + 1, y, truncate_str(text, max(0, right - label_x - label_w - 1)),
                         Style(dim=True), max_width=max(0, right - label_x - label_w - 1))
        return 2


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
        more_txt = t("more", state.lang, count=add_more)
        canvas.draw_text(0, y, more_txt, Style(dim=True), max_width=width)
        y += 1
    return y


def agent_table_layout(width: int) -> Tuple[int, int]:
    """Compute ``(agent_col_width, share_bar_len)`` for the Agents table.

    Sizes columns so the share percentage (``100.0%`` = 6 cells) is always
    fully visible; on narrow terminals the share bar shrinks first and is
    dropped before the percentage is clipped.
    """
    # Fixed columns + gaps: SESSIONS(8) + TOKENS(8) + COST(10) + SPEED(8) + TTFT(7) + PCT(6) + gaps(7) = 54
    fixed_no_bar = 54
    rem = max(0, width - fixed_no_bar)
    min_ag = 16
    min_bar = 4  # '[' + bar + '] ' needs bar_len + 3 cells
    if rem >= min_ag + min_bar + 3:
        bar_len = min(16, rem - min_ag - 3)
        ag_w = rem - (bar_len + 3)
    else:
        bar_len = 0
        ag_w = max(6, rem)
    return ag_w, bar_len


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
    detail_vm: Optional[Union[ProjectDetailViewModel, AgentDetailViewModel]] = None,
    static_mode: bool = False,
) -> List[HitBox]:
    """Render the full TUI layout onto canvas.

    Returns the clickable regions (see :data:`HitBox`) so the terminal layer
    can turn mouse events into the same actions as the keyboard, and so the
    mapping is testable without a real terminal.
    """
    width = canvas.width
    height = canvas.height
    lang = normalize_lang(state.lang)
    hit_boxes: List[HitBox] = []

    # 1. Terminal too small check (< 60 cols or < 15 rows)
    if width < 60 or height < 15:
        msg = t("terminal_too_small", state.lang, width=width, height=height)
        canvas.draw_text(0, 0, truncate_str(msg, width), Style(bold=True, fg="yellow"))
        return hit_boxes

    if filtered is None:
        # Immediate Loading screen
        ver_str = f"Kanjo {state.version}"
        cur_x = canvas.draw_text(0, 0, ver_str, Style(bold=True, fg="cyan"))
        cur_x = canvas.draw_text(cur_x, 0, " · ", Style(dim=True))

        for idx, (r_val, r_label) in enumerate(RANGE_TABS):
            is_active = (state.time_range == r_val)
            tab_str = f" {t('range.' + r_val.value, state.lang)} "
            tab_style = _active_tab_style(state) if is_active else Style()
            tab_start = cur_x
            cur_x = canvas.draw_text(cur_x, 0, tab_str, tab_style)
            _add_hit_box(hit_boxes, 0, tab_start, cur_x - 1,
                         "range:" + r_val.value, width)
            if idx < len(RANGE_TABS) - 1:
                cur_x = canvas.draw_text(cur_x, 0, " ", Style())

        load_failed = bool(state.load_error) and not state.is_scanning
        if not load_failed:
            spin = ASCII_SPINNER[state.spinner_frame % len(ASCII_SPINNER)] if state.ascii_mode else SPINNER_CHARS[state.spinner_frame % len(SPINNER_CHARS)]
            right_str = f"{spin} {t('loading', state.lang)}"
            rw = str_width(right_str)
            if width - rw > cur_x + 1:
                canvas.draw_text(width - rw, 0, right_str, Style(fg="yellow"))

        ly = height // 2
        if load_failed:
            err_msg = truncate_str(t("refresh.error", state.lang, error=state.load_error), width)
            lx = max(0, (width - str_width(err_msg)) // 2)
            canvas.draw_text(lx, ly, err_msg, Style(bold=True, fg="red"))
            hint = truncate_str(t("loading.retry_hint", state.lang), width)
            hx = max(0, (width - str_width(hint)) // 2)
            canvas.draw_text(hx, ly + 1, hint, Style(dim=True))
        else:
            load_msg = t("loading", state.lang)
            lx = max(0, (width - str_width(load_msg)) // 2)
            canvas.draw_text(lx, ly, load_msg, Style(bold=True, fg="cyan"))

        bar_y = height - 1
        canvas.fill_rect(0, bar_y, width, 1, " ", Style())
        bx = 0
        for key_lbl, name_lbl in [("F1", t("fkey.help", state.lang)), ("F10", t("fkey.quit", state.lang))]:
            if bx >= width:
                break
            item_start = bx
            k_style = Style(bold=True)
            bx = canvas.draw_text(bx, bar_y, f"{key_lbl}", k_style)
            n_style = _fkey_name_style(state)
            bx = canvas.draw_text(bx, bar_y, f"{name_lbl} ", n_style)
            _add_hit_box(hit_boxes, bar_y, item_start, bx - 1,
                         "fkey:" + key_lbl, width)
        return hit_boxes

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
        tab_str = f" {t('range.' + r_val.value, state.lang)} "
        if is_active:
            tab_style = _active_tab_style(state)
        else:
            tab_style = Style()
        tab_start = cur_x
        cur_x = canvas.draw_text(cur_x, cur_y, tab_str, tab_style)
        _add_hit_box(hit_boxes, cur_y, tab_start, cur_x - 1,
                     "range:" + r_val.value, width)
        if idx < len(RANGE_TABS) - 1:
            cur_x = canvas.draw_text(cur_x, cur_y, " ", Style())

    # Right side: refresh time and spinner
    right_items = []
    if state.is_stale:
        spin = ASCII_SPINNER[state.spinner_frame % len(ASCII_SPINNER)] if state.ascii_mode else SPINNER_CHARS[state.spinner_frame % len(SPINNER_CHARS)]
        right_items.append(f"{spin} {t('stale', state.lang, time=state.last_generated_at_str)}")
    elif state.is_scanning:
        spin = ASCII_SPINNER[state.spinner_frame % len(ASCII_SPINNER)] if state.ascii_mode else SPINNER_CHARS[state.spinner_frame % len(SPINNER_CHARS)]
        right_items.append(f"{spin} {t('refreshing', state.lang)}")
    
    if state.last_refresh_time and not state.is_stale:
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

    # Bottom reserved rows: 1 row for F-key bar, plus 1 if filter prompt active.
    # Static snapshots have no chrome: the table may use the full height.
    if static_mode:
        bottom_reserved = 0
    else:
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
        label_w = _meter_label_width(meters, meter_mode,
                                     (width - 2) // 2 if two_col else width)
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

    # 5. Antigravity Accounts summary (only outside the dedicated Accounts view)
    if (accounts_section and state.view_mode != ViewMode.ACCOUNTS
            and cur_y < content_limit_y):
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
                    cur_marker = "  " + t("accounts.ascii_current" if state.ascii_mode else "accounts.current", lang)
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

        h_proj = pad_str(t("col.project", lang), proj_w)
        h_cost = pad_str(t("col.cost", lang), 10, align="right")
        h_tok = pad_str(t("col.tokens", lang), 8, align="right")
        h_sess = pad_str(t("col.sessions", lang), 8, align="right")
        h_ag = pad_str(t("col.agents", lang), 8, align="center")
        h_last = pad_str(t("col.last_active", lang), 11, align="right")
        h_8w = pad_str(t("col.week8", lang), 8, align="center")

        h_line = f"{h_proj} {h_cost} {h_tok} {h_sess} {h_ag} {h_last} {h_8w}"
        canvas.fill_rect(0, table_header_y, width, 1, " ", header_style)
        canvas.draw_text(0, table_header_y, h_line[:width], header_style)
        # Clicking a column header sorts by it (a second click flips the
        # direction). Only the sortable columns are clickable, and the x ranges
        # mirror the ones the rows below are drawn with.
        if not static_mode:
            for col, x0, x1 in (("name", 0, proj_w - 1),
                                ("cost", proj_w + 1, proj_w + 10),
                                ("tokens", proj_w + 12, proj_w + 19),
                                ("sessions", proj_w + 21, proj_w + 28)):
                _add_hit_box(hit_boxes, table_header_y, x0, x1, "sort:" + col, width)
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
            is_sel = (not static_mode) and (scroll_offset + idx == state.selected_index)
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

        if not static_mode:
            for idx in range(len(shown_projects)):
                _add_hit_box(hit_boxes, cur_y + idx, 0, width - 1,
                             "row:%d" % (scroll_offset + idx), width)

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
        h_mod = pad_str(t("col.model", lang), mod_w)
        h_prov = pad_str(t("col.provider", lang), 15)
        h_tok = pad_str(t("col.tokens", lang), 10, align="right")
        h_cost = pad_str(t("col.cost", lang), 10, align="right")
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

        scroll_offset = 0 if static_mode else state.scroll_top
        shown_models = model_rows[scroll_offset:scroll_offset + body_height] if not static_mode else model_rows[:min(15, body_height)]

        for idx, row in enumerate(shown_models):
            row_y = cur_y + idx
            is_sel = (not static_mode) and (scroll_offset + idx == state.selected_index)
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

        if not static_mode:
            for idx in range(len(shown_models)):
                _add_hit_box(hit_boxes, cur_y + idx, 0, width - 1,
                             "row:%d" % (scroll_offset + idx), width)

    elif state.view_mode == ViewMode.AGENTS:
        # Columns: AGENT, SESSIONS, TOKENS, COST, SPEED, TTFT, SHARE
        ag_w, bar_len = agent_table_layout(width)
        share_w = (bar_len + 9) if bar_len > 0 else 6
        h_ag = pad_str(t("col.agent", lang), ag_w)
        h_sess = pad_str(t("col.sessions", lang), 8, align="right")
        h_tok = pad_str(t("col.tokens", lang), 8, align="right")
        h_cost = pad_str(t("col.cost", lang), 10, align="right")
        h_spd = pad_str(t("col.speed", lang), 8, align="right")
        h_ttft = pad_str(t("col.ttft", lang), 7, align="right")
        h_share = pad_str(t("col.share", lang), share_w, align="left" if bar_len > 0 else "right")
        h_line = f"{h_ag} {h_sess} {h_tok} {h_cost} {h_spd} {h_ttft}  {h_share}"
        canvas.fill_rect(0, table_header_y, width, 1, " ", header_style)
        canvas.draw_text(0, table_header_y, truncate_str(h_line, width), header_style)
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

        scroll_offset = 0 if static_mode else state.scroll_top
        shown_agents = agent_rows[scroll_offset:scroll_offset + body_height] if not static_mode else agent_rows[:min(15, body_height)]

        for idx, row in enumerate(shown_agents):
            row_y = cur_y + idx
            is_sel = (not static_mode) and (scroll_offset + idx == state.selected_index)
            row_style = _selected_row_style(state) if is_sel else Style()
            if is_sel:
                canvas.fill_rect(0, row_y, width, 1, " ", row_style)

            canvas.draw_text(0, row_y, pad_str(truncate_str(row.label, ag_w), ag_w), row_style)
            rx = ag_w + 1
            canvas.draw_text(rx, row_y, pad_str(row.sessions_str, 8, align="right"), row_style)
            rx += 9
            canvas.draw_text(rx, row_y, pad_str(row.tokens_str, 8, align="right"), row_style)
            rx += 9
            canvas.draw_text(rx, row_y, pad_str(row.cost_str, 10, align="right"), row_style)
            rx += 11
            spd_style = _on_selected_row(state, is_sel, Style(dim=(row.speed_str == "—")))
            canvas.draw_text(rx, row_y, pad_str(row.speed_str, 8, align="right"), spd_style)
            rx += 9
            ttft_style = _on_selected_row(state, is_sel, Style(dim=(row.ttft_str == "—")))
            canvas.draw_text(rx, row_y, pad_str(row.ttft_str, 7, align="right"), ttft_style)
            rx += 9

            # Share bar [████░░░░] 45.2% (drop bar on narrow widths, always show %)
            pct_str = f"{row.share_pct:5.1f}%"
            if bar_len > 0:
                filled = min(bar_len, max(0, int(round((row.share_pct / 100.0) * bar_len))))
                empty = bar_len - filled
                canvas.draw_text(rx, row_y, "[", _on_selected_row(state, is_sel, Style(dim=True)))
                block_ch = "=" if state.ascii_mode else "█"
                canvas.draw_text(rx + 1, row_y, block_ch * filled,
                                 _on_selected_row(state, is_sel, Style(fg=row.color, bold=True)))
                canvas.draw_text(rx + 1 + filled, row_y, " " * empty,
                                 _on_selected_row(state, is_sel, Style()))
                canvas.draw_text(rx + 1 + bar_len, row_y, "]",
                                 _on_selected_row(state, is_sel, Style(dim=True)))
                canvas.draw_text(rx + 3 + bar_len, row_y, pct_str, row_style)
            else:
                canvas.draw_text(rx, row_y, pct_str, row_style)

        if not static_mode:
            for idx in range(len(shown_agents)):
                _add_hit_box(hit_boxes, cur_y + idx, 0, width - 1,
                             "row:%d" % (scroll_offset + idx), width)

    elif state.view_mode == ViewMode.DAYS:
        # Columns: DATE, COST BAR, COST, TOKENS
        h_date = pad_str(t("col.date", lang), 12)
        h_cost = pad_str(t("col.cost", lang), 10, align="right")
        h_tok = pad_str(t("col.tokens", lang), 10, align="right")
        bar_len = min(30, max(10, width - 40))
        h_bar = pad_str(t("col.cost_bar", lang), bar_len + 2)
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

        scroll_offset = 0 if static_mode else state.scroll_top
        shown_days = day_rows[scroll_offset:scroll_offset + body_height] if not static_mode else day_rows[:min(15, body_height)]

        for idx, row in enumerate(shown_days):
            row_y = cur_y + idx
            is_sel = (not static_mode) and (scroll_offset + idx == state.selected_index)
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

        if not static_mode:
            for idx in range(len(shown_days)):
                _add_hit_box(hit_boxes, cur_y + idx, 0, width - 1,
                             "row:%d" % (scroll_offset + idx), width)

    elif state.view_mode == ViewMode.ACCOUNTS:
        sec = accounts_section
        # Title shows the accounting window (quota week / billing cycle / 7d).
        if sec is None:
            pass
        else:
            canvas.draw_text(0, table_header_y,
                             truncate_str(sec.header_label, width),
                             Style(bold=True, fg="white"))
            table_header_y += 1
            cur_y = table_header_y

            # ``10月28日 02:25`` is one column wider than ``Oct 28 02:25``.
            seen_w = 14 if lang == "zh" else 13
            fixed_w = 61 + (seen_w - 13)
            email_w = max(16, width - fixed_w)
            h_line = (pad_str(t("col.account", lang), email_w) + " "
                      + pad_str(t("col.tokens", lang), 9, align="right") + " "
                      + pad_str(t("col.cost", lang), 10, align="right") + " "
                      + pad_str(t("col.messages", lang), 8, align="right") + " "
                      + pad_str(t("col.last_seen", lang), seen_w, align="right") + " "
                      + pad_str(t("col.login", lang), 6))
            canvas.fill_rect(0, table_header_y, width, 1, " ", header_style)
            canvas.draw_text(0, table_header_y, truncate_str(h_line, width), header_style)
            cur_y += 1

            body_height = max(0, table_bottom_y - cur_y)
            total_items = len(sec.rows)
            if not static_mode:
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
                shown_accounts = sec.rows[scroll_offset:scroll_offset + body_height]
            else:
                scroll_offset = 0
                shown_accounts = sec.rows[:min(15, body_height)]

            for idx, row in enumerate(shown_accounts):
                row_y = cur_y + idx
                is_sel = (not static_mode) and (scroll_offset + idx == state.selected_index)
                row_style = _selected_row_style(state) if is_sel else Style()
                if is_sel:
                    canvas.fill_rect(0, row_y, width, 1, " ", row_style)
                base_style = Style(dim=True) if row.is_unattributed else row_style

                canvas.draw_text(0, row_y, pad_str(truncate_str(row.email, email_w), email_w), base_style)
                rx = email_w + 1
                canvas.draw_text(rx, row_y, pad_str(row.tokens_str, 9, align="right"), base_style)
                rx += 10
                canvas.draw_text(rx, row_y, pad_str(row.cost_str, 10, align="right"), base_style)
                rx += 11
                canvas.draw_text(rx, row_y, pad_str(row.messages_str, 8, align="right"), base_style)
                rx += 9
                canvas.draw_text(rx, row_y, pad_str(row.last_seen_str, seen_w, align="right"), base_style)
                rx += seen_w + 1
                if row.is_unattributed:
                    login_str = "—"
                else:
                    login_str = t("bool.yes", lang) if row.saved_login else t("bool.no", lang)
                canvas.draw_text(rx, row_y, pad_str(login_str, 6), base_style)
                rx += 7
                if row.is_current:
                    marker_txt = t("accounts.ascii_current" if state.ascii_mode else "accounts.current", lang)
                    m_style = _on_selected_row(state, is_sel, Style(fg="green", bold=True))
                    canvas.draw_text(rx, row_y, truncate_str(marker_txt, max(0, width - rx)), m_style)

            if not static_mode:
                for idx in range(len(shown_accounts)):
                    _add_hit_box(hit_boxes, cur_y + idx, 0, width - 1,
                                 "row:%d" % (scroll_offset + idx), width)

    # 7. Filter input bar (if active)
    if state.filter_active:
        fy = height - 2
        f_prompt = t("filter_prompt", lang, query=state.filter_input)
        filter_style = _filter_prompt_style(state)
        canvas.fill_rect(0, fy, width, 1, " ", filter_style)
        canvas.draw_text(1, fy, f_prompt[:width - 2], filter_style)

    # 8. F-key Bar (last line, y = height - 1)
    # F1Help F2Range F3View F4Filter F5Refresh F6Sort F10Quit
    bar_y = height - 1
    f_items = [
        ("F1", t("fkey.help", lang)),
        ("F2", t("fkey.range", lang)),
        ("F3", t("fkey.view", lang)),
        ("F4", t("fkey.filter", lang)),
        ("F5", t("fkey.refresh", lang)),
        ("F6", t("fkey.sort", lang)),
        ("F7", t("fkey.meters", lang)),
        ("F10", t("fkey.quit", lang)),
    ]
    if not static_mode:
        canvas.fill_rect(0, bar_y, width, 1, " ", Style())
        bx = 0
        for key_lbl, name_lbl in f_items:
            if bx >= width:
                break
            item_start = bx
            k_style = Style(bold=True)
            bx = canvas.draw_text(bx, bar_y, f"{key_lbl}", k_style)
            n_style = _fkey_name_style(state)
            bx = canvas.draw_text(bx, bar_y, f"{name_lbl} ", n_style)
            _add_hit_box(hit_boxes, bar_y, item_start, bx - 1,
                         "fkey:" + key_lbl, width)

    # 9. Detail Pane Overlay
    if state.detail_open and isinstance(detail_vm, AgentDetailViewModel):
        _render_agent_detail_pane(canvas, state, detail_vm, lang)
    elif state.detail_open and detail_vm is not None:
        dw = min(width - 4, 80)
        dh = min(height - 4, 22)
        dx = (width - dw) // 2
        dy = (height - dh) // 2

        # One background for the whole pane: every cell inside the border gets
        # it (including gaps between text runs), and all text drawn below keeps
        # it, so the pane reads as a solid block.
        def pane(fg=None, bold=False, dim=False) -> Style:
            return Style(fg=fg, bg=DETAIL_PANE_BG, bold=bold, dim=dim)

        canvas.draw_box(dx, dy, dw, dh, title=t("detail.title", lang, name=detail_vm.name),
                        style=pane(fg="white"),
                        border_style=Style(fg="cyan", bold=True),
                        ascii_mode=state.ascii_mode)
        canvas.fill_rect(dx + 1, dy + 1, dw - 2, dh - 2, " ", pane(fg="white"))

        cy = dy + 1
        if detail_vm.remote:
            canvas.draw_text(dx + 2, cy, t("detail.remote", lang, remote=detail_vm.remote), pane(fg="gray"), max_width=dw - 4)
            cy += 1
        if detail_vm.paths:
            p_str = ", ".join(detail_vm.paths)
            canvas.draw_text(dx + 2, cy, t("detail.paths", lang, paths=p_str), pane(fg="gray"), max_width=dw - 4)
            cy += 1

        stats_line = t("detail.stats", lang, cost=detail_vm.cost_str,
                       tokens=detail_vm.tokens_str, sessions=detail_vm.sessions_str)
        canvas.draw_text(dx + 2, cy, stats_line, pane(bold=True), max_width=dw - 4)
        cy += 1

        spark_line = t("detail.sparkline", lang, spark=detail_vm.sparkline_30d,
                       peak=detail_vm.sparkline_peak_str)
        canvas.draw_text(dx + 2, cy, spark_line, pane(fg="cyan"), max_width=dw - 4)
        cy += 1

        # Divider
        canvas.draw_hline(dx + 1, cy, dw - 2, "─" if not state.ascii_mode else "-", pane(dim=True))
        cy += 1

        # By Agent
        canvas.draw_text(dx + 2, cy, t("detail.by_agent", lang), pane(bold=True))
        cy += 1
        for lbl, c, tok_str, sess_str, pct, rgb in detail_vm.by_agent[:4]:
            if cy >= dy + dh - 7:
                break
            dot = "*" if state.ascii_mode else "●"
            ag_line = f"  {dot} {pad_str(lbl, 16)}  {pad_str(c, 10, align='right')}  {pad_str(tok_str, 8, align='right')}  {pad_str(sess_str, 4, align='right')}  ({pct:.1f}%)"
            canvas.draw_text(dx + 2, cy, f"  {dot} ", pane(fg=rgb, bold=True))
            canvas.draw_text(dx + 6, cy, ag_line[4:], pane())
            cy += 1

        # Divider
        canvas.draw_hline(dx + 1, cy, dw - 2, "─" if not state.ascii_mode else "-", pane(dim=True))
        cy += 1

        # By Model
        canvas.draw_text(dx + 2, cy, t("detail.by_model", lang), pane(bold=True))
        cy += 1
        for m_name, prov, c, tok_str in detail_vm.by_model[:4]:
            if cy >= dy + dh - 3:
                break
            m_line = f"  {pad_str(truncate_str(m_name, 22), 22)}  {pad_str(prov, 12)}  {pad_str(c, 10, align='right')}  {pad_str(tok_str, 8, align='right')}"
            canvas.draw_text(dx + 2, cy, m_line, pane())
            cy += 1

        # Close note at bottom of detail pane
        close_note = t("detail.close", lang)
        canvas.draw_text(dx + max(1, (dw - str_width(close_note)) // 2), dy + dh - 2,
                         truncate_str(close_note, dw - 2), pane(dim=True))

    # 10. Help Overlay
    if state.show_help:
        hw = max(24, min(width - 4, 76))
        hx = (width - hw) // 2
        title_col_w = 12
        desc_x_off = 2 + title_col_w + 2
        desc_w = max(8, hw - desc_x_off - 2)

        help_lines = [
            (t("help.navigation.title", lang), t("help.navigation.desc", lang)),
            (t("help.range.title", lang), t("help.range.desc", lang)),
            (t("help.views.title", lang), t("help.views.desc", lang)),
            (t("help.detail.title", lang), t("help.detail.desc", lang)),
            (t("help.filter.title", lang), t("help.filter.desc", lang)),
            (t("help.sort.title", lang), t("help.sort.desc", lang)),
            (t("help.meters.title", lang), t("help.meters.desc", lang)),
            (t("help.refresh.title", lang), t("help.refresh.desc", lang)),
            (t("help.mouse.title", lang), t("help.mouse.desc", lang)),
            (t("help.quit.title", lang), t("help.quit.desc", lang)),
        ]

        wrapped = []
        for title_str, desc in help_lines:
            rows = wrap_display(desc, desc_w)
            wrapped.append((title_str, rows))

        needed = 2 + sum(len(rows) for _, rows in wrapped) + 2
        hh = max(8, min(height - 4, needed))
        hy = (height - hh) // 2

        # Clear the full rows behind the overlay so no text bleeds around the box.
        canvas.fill_rect(0, hy, width, hh, " ", Style())

        canvas.draw_box(hx, hy, hw, hh, title=t("help.title", lang),
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

        close_note = t("help.close", lang)
        note_x = hx + max(1, (hw - str_width(close_note)) // 2)
        canvas.draw_text(note_x, hy + hh - 2, truncate_str(close_note, hw - 2),
                         Style(dim=True), max_width=max(0, hx + hw - 1 - note_x))

    # 11. One-line status above the F-key bar (expires by itself)
    if (not static_mode and state.status_message
            and (state.status_until <= 0 or time.time() < state.status_until)):
        sy = height - 2
        if state.filter_active:
            sy = height - 3
        canvas.fill_rect(0, sy, width, 1, " ", Style())
        canvas.draw_text(0, sy, truncate_str(state.status_message, width),
                         Style(bold=True, fg="yellow"), max_width=width)

    # 12. Antigravity login switch confirmation (small centred box)
    if state.confirm_switch_email:
        msg = t("accounts.confirm", lang, email=state.confirm_switch_email)
        dw = max(24, min(width - 4, 72))
        inner_w = max(8, dw - 4)
        lines = wrap_display(msg, inner_w)
        dh = len(lines) + 3
        dh = min(height - 2, dh)
        dx = (width - dw) // 2
        dy = (height - dh) // 2
        canvas.fill_rect(dx, dy, dw, dh, " ", Style())
        canvas.draw_box(dx, dy, dw, dh, title=t("accounts.confirm_title", lang),
                        style=Style(bg="black", fg="white"),
                        border_style=Style(fg="yellow", bold=True),
                        ascii_mode=state.ascii_mode)
        cy = dy + 2
        for line in lines:
            if cy >= dy + dh - 1:
                break
            canvas.draw_text(dx + 2, cy, line, Style(), max_width=inner_w + 1)
            cy += 1

    return hit_boxes


def _render_agent_detail_pane(
    canvas: Canvas,
    state: TUIState,
    vm: AgentDetailViewModel,
    lang: str,
) -> None:
    """Render the Agent detail overlay pane with solid background inside border."""
    width = canvas.width
    height = canvas.height
    dw = min(width - 4, 80)
    model_rows_count = len(vm.models) + (1 if vm.others_model else 0)
    extra_acc_h = (2 + len(vm.account_shares)) if vm.account_shares else 0
    extra_model_h = max(0, model_rows_count - 6)
    max_dh = 25 + extra_acc_h + extra_model_h
    dh = min(height - 4, max_dh)
    dx = (width - dw) // 2
    dy = (height - dh) // 2
    iw = max(10, dw - 4)
    left_x = dx + 2
    right_x = left_x + iw
    last_cy = dy + dh - 2  # reserved for close hint
    hline_ch = "-" if state.ascii_mode else "─"
    dot = "*" if state.ascii_mode else "●"
    block_ch = "=" if state.ascii_mode else "█"
    leg_dot = "*" if state.ascii_mode else "■"

    def pane(fg=None, bold=False, dim=False) -> Style:
        return Style(fg=fg, bg=DETAIL_PANE_BG, bold=bold, dim=dim)

    canvas.draw_box(
        dx, dy, dw, dh,
        title=t("agent_detail.title", lang, name=vm.label),
        style=pane(fg="white"),
        border_style=Style(fg="cyan", bold=True),
        ascii_mode=state.ascii_mode,
    )
    canvas.fill_rect(dx + 1, dy + 1, dw - 2, dh - 2, " ", pane(fg="white"))

    cy = dy + 1
    if cy >= last_cy:
        close_note = t("detail.close", lang)
        canvas.draw_text(dx + max(1, (dw - str_width(close_note)) // 2), dy + dh - 2,
                         truncate_str(close_note, dw - 2), pane(dim=True))
        return

    # 1. Header: colour dot + agent label + plan label/price + multiplier; right-side summary if room
    cx = canvas.draw_text(left_x, cy, f"{dot} ", pane(fg=vm.color, bold=True), max_width=right_x - left_x)
    cx = canvas.draw_text(cx, cy, truncate_str(vm.label, max(0, right_x - cx)),
                          pane(fg="white", bold=True), max_width=max(0, right_x - cx))
    if vm.plan_label and cx < right_x:
        plan_txt = f" · {vm.plan_label}"
        if vm.price_str:
            plan_txt += f" ({vm.price_str})"
        mult_reserve = (str_width(f" · {vm.multiplier_str}") if vm.multiplier_str else 0)
        avail_plan = max(0, right_x - cx - mult_reserve)
        if avail_plan > 3:
            cx = canvas.draw_text(cx, cy, truncate_str(plan_txt, avail_plan),
                                  pane(fg="gray"), max_width=avail_plan)
        if vm.multiplier_str and cx < right_x:
            cx = canvas.draw_text(cx, cy, " · ", pane(fg="gray"), max_width=max(0, right_x - cx))
            cx = canvas.draw_text(cx, cy, vm.multiplier_str,
                                  pane(fg=vm.color, bold=True), max_width=max(0, right_x - cx))
    summary_txt = f"{vm.cost_str} · {vm.tokens_str}"
    sw = str_width(summary_txt)
    if cx + 2 + sw <= right_x:
        canvas.draw_text(right_x - sw, cy, summary_txt, pane(fg="gray"), max_width=sw)
    cy += 1

    # 2. Tokens breakdown + cache hit
    if cy < last_cy:
        canvas.draw_hline(dx + 1, cy, dw - 2, hline_ch, pane(dim=True))
        cy += 1
    if cy < last_cy:
        tok_title = t("agent_detail.tokens", lang)
        hit_txt = t("agent_detail.cache_hit", lang, value=vm.cache_hit_str)
        canvas.draw_text(left_x, cy, tok_title, pane(bold=True), max_width=iw)
        hw = str_width(hit_txt)
        if str_width(tok_title) + 2 + hw <= iw:
            canvas.draw_text(right_x - hw, cy, hit_txt, pane(fg="cyan" if vm.cache_hit_rate is not None else "gray"), max_width=hw)
        cy += 1
    if cy < last_cy:
        tok_items = [
            (t("agent_detail.input", lang), vm.input_str),
            (t("agent_detail.output", lang), vm.output_str),
            (t("agent_detail.cache_read", lang), vm.cache_read_str),
            (t("agent_detail.cache_write", lang), vm.cache_write_str),
        ]
        single_parts = [f"{lbl} {val}" for lbl, val in tok_items]
        single_line = "  " + "  ".join(single_parts)
        if str_width(single_line) <= iw:
            tx = left_x + 2
            for idx_t, (lbl, val) in enumerate(tok_items):
                if idx_t > 0:
                    tx = canvas.draw_text(tx, cy, "  ", pane(), max_width=max(0, right_x - tx))
                tx = canvas.draw_text(tx, cy, f"{lbl} ", pane(fg="gray"), max_width=max(0, right_x - tx))
                tx = canvas.draw_text(tx, cy, val, pane(fg="white", bold=True), max_width=max(0, right_x - tx))
            cy += 1
        else:
            col_w = max(10, (iw - 2) // 2)
            for pair in (tok_items[:2], tok_items[2:]):
                if cy >= last_cy:
                    break
                tx = left_x + 2
                for idx_p, (lbl, val) in enumerate(pair):
                    cell_x = tx + idx_p * col_w
                    px = canvas.draw_text(cell_x, cy, f"{lbl} ", pane(fg="gray"),
                                          max_width=max(0, right_x - cell_x))
                    canvas.draw_text(px, cy, val, pane(fg="white", bold=True),
                                     max_width=max(0, right_x - px))
                cy += 1

    # 3. Performance
    if cy < last_cy:
        canvas.draw_hline(dx + 1, cy, dw - 2, hline_ch, pane(dim=True))
        cy += 1
    if cy < last_cy:
        perf_title = t("agent_detail.performance", lang)
        canvas.draw_text(left_x, cy, perf_title, pane(bold=True), max_width=iw)
        sw = str_width(vm.samples_str)
        if str_width(perf_title) + 2 + sw <= iw:
            canvas.draw_text(right_x - sw, cy, vm.samples_str,
                             pane(fg="gray", dim=(vm.perf_samples == 0)), max_width=sw)
        cy += 1
    if cy < last_cy:
        tx = left_x + 2
        tx = canvas.draw_text(tx, cy, t("agent_detail.output_speed", lang), pane(fg="gray"),
                              max_width=max(0, right_x - tx))
        tx = canvas.draw_text(tx, cy, vm.speed_str,
                              pane(fg="white", bold=(vm.tps is not None), dim=(vm.tps is None)),
                              max_width=max(0, right_x - tx))
        tx = canvas.draw_text(tx, cy, "   ", pane(), max_width=max(0, right_x - tx))
        tx = canvas.draw_text(tx, cy, t("agent_detail.ttft_median", lang), pane(fg="gray"),
                              max_width=max(0, right_x - tx))
        canvas.draw_text(tx, cy, vm.ttft_str,
                         pane(fg="white", bold=(vm.ttft_median is not None), dim=(vm.ttft_median is None)),
                         max_width=max(0, right_x - tx))
        cy += 1

    # Build legend items for "Where the money went" so we reserve exact vertical lines
    leg_items: List[Tuple[Tuple[int, int, int], str]] = [
        (seg.color, f"{seg.project_name} {seg.share_str}")
        for seg in vm.project_shares
    ]
    if vm.others_project_share:
        others = vm.others_project_share
        leg_items.append((
            others.color,
            f"{t('agent_detail.others', lang, count=others.count)} {others.share_str}",
        ))
    leg_lines = 0
    if leg_items:
        leg_lines = 1
        lx_sim = 0
        for _rgb, text in leg_items:
            prefix_w = 0 if lx_sim == 0 else 2
            item_w = prefix_w + str_width(leg_dot) + 1 + str_width(text)
            if lx_sim > 0 and lx_sim + item_w > iw:
                leg_lines += 1
                lx_sim = str_width(leg_dot) + 1 + str_width(text)
            else:
                lx_sim += item_w
    reserve_money = (3 + leg_lines) if vm.project_shares else 3

    # 3b. By account (Antigravity only, omitted when empty)
    if vm.account_shares and cy + 3 <= last_cy:
        canvas.draw_hline(dx + 1, cy, dw - 2, hline_ch, pane(dim=True))
        cy += 1
        canvas.draw_text(left_x, cy, t("agent_detail.by_account", lang), pane(bold=True), max_width=iw)
        cy += 1

        bar_len = 12 if iw >= 58 else max(4, iw - 44)
        # 2(indent) + name_w + 1 + 8(tokens) + 1 + (bar_len+2) + 1 + 4(pct) + 1 + 10(cost) = iw
        name_w = max(6, iw - 30 - bar_len)
        avail_rows = last_cy - cy
        max_accounts = (avail_rows - reserve_money) if (avail_rows - reserve_money >= 1) else avail_rows
        for acc in vm.account_shares[:max_accounts]:
            if cy >= last_cy:
                break
            ax = left_x + 2
            name_txt = pad_str(truncate_str(acc.display_name, name_w), name_w)
            if acc.is_dimmed:
                name_style = pane(fg="gray", dim=True)
            elif acc.is_unattributed:
                name_style = pane(fg="gray")
            else:
                name_style = pane()
            canvas.draw_text(ax, cy, name_txt, name_style, max_width=name_w)

            rx = ax + name_w + 1
            tok_style = pane(fg="gray", dim=True) if acc.is_dimmed else pane()
            canvas.draw_text(rx, cy, pad_str(acc.tokens_str, 8, align="right"), tok_style, max_width=8)
            rx += 9

            filled = 0 if acc.is_dimmed else min(bar_len, max(0, int(round(acc.share * bar_len))))
            empty = bar_len - filled
            canvas.draw_text(rx, cy, "[", pane(dim=True), max_width=1)
            if filled > 0:
                bar_fg = "gray" if acc.is_unattributed else vm.color
                canvas.draw_text(rx + 1, cy, block_ch * filled, pane(fg=bar_fg, bold=True), max_width=filled)
            if empty > 0:
                canvas.draw_text(rx + 1 + filled, cy, " " * empty, pane(dim=acc.is_dimmed), max_width=empty)
            canvas.draw_text(rx + 1 + bar_len, cy, "]", pane(dim=True), max_width=1)
            rx += bar_len + 3

            if acc.is_dimmed:
                pct_style = pane(fg="gray", dim=True)
            elif acc.is_unattributed:
                pct_style = pane(fg="gray", bold=True)
            else:
                pct_style = pane(fg=vm.color, bold=True)
            canvas.draw_text(rx, cy, pad_str(acc.share_str, 4, align="right"), pct_style, max_width=4)
            rx += 5

            cost_style = pane(fg="gray", dim=True) if acc.is_dimmed else pane(bold=True)
            canvas.draw_text(rx, cy, pad_str(acc.cost_str, 10, align="right"), cost_style,
                             max_width=max(0, right_x - rx))
            cy += 1

    # 4. Per-model table
    if vm.models and cy + 4 <= last_cy - reserve_money:
        canvas.draw_hline(dx + 1, cy, dw - 2, hline_ch, pane(dim=True))
        cy += 1
        canvas.draw_text(left_x, cy, t("agent_detail.models", lang), pane(bold=True), max_width=iw)
        cy += 1

        # Right columns: TOKENS(8) HIT(5) SPEED(8) COST(10) + gaps(4) + indent(2) = 37
        mod_w = max(10, iw - 37)
        mh_line = (
            "  "
            + pad_str(t("col.model", lang), mod_w) + " "
            + pad_str(t("col.tokens", lang), 8, align="right") + " "
            + pad_str(t("agent_detail.models.hit", lang), 5, align="right") + " "
            + pad_str(t("agent_detail.models.speed", lang), 8, align="right") + " "
            + pad_str(t("col.cost", lang), 10, align="right")
        )
        canvas.draw_text(left_x, cy, truncate_str(mh_line, iw), pane(fg="gray", dim=True), max_width=iw)
        cy += 1

        max_models = max(1, (last_cy - reserve_money) - cy)
        for m in vm.models[:max_models]:
            if cy >= last_cy - reserve_money:
                break
            mx = left_x + 2
            if m.estimated:
                est_txt = " " + t("agent_detail.estimated", lang)
                est_w = str_width(est_txt)
                name_max = max(4, mod_w - est_w)
                name_part = truncate_str(m.model, name_max)
                mx = canvas.draw_text(mx, cy, name_part, pane(), max_width=name_max)
                mx = canvas.draw_text(mx, cy, est_txt, pane(fg="yellow"), max_width=est_w)
                rem_pad = mod_w - (str_width(name_part) + est_w)
                if rem_pad > 0:
                    canvas.draw_text(mx, cy, " " * rem_pad, pane(), max_width=rem_pad)
            else:
                canvas.draw_text(mx, cy, pad_str(truncate_str(m.model, mod_w), mod_w), pane(), max_width=mod_w)

            rx = left_x + 2 + mod_w + 1
            canvas.draw_text(rx, cy, pad_str(m.tokens_str, 8, align="right"), pane(), max_width=8)
            rx += 9
            canvas.draw_text(rx, cy, pad_str(m.hit_str, 5, align="right"),
                             pane(fg="gray", dim=(m.hit_str == "—")), max_width=5)
            rx += 6
            canvas.draw_text(rx, cy, pad_str(m.speed_str, 8, align="right"),
                             pane(fg="gray", dim=(m.speed_str == "—")), max_width=8)
            rx += 9
            canvas.draw_text(rx, cy, pad_str(m.cost_str, 10, align="right"), pane(bold=True), max_width=max(0, right_x - rx))
            cy += 1

        if vm.others_model and len(vm.models) <= max_models and cy < last_cy - reserve_money:
            om = vm.others_model
            others_lbl = t("agent_detail.models.others", lang, count=om.count)
            canvas.draw_text(left_x + 2, cy, pad_str(truncate_str(others_lbl, mod_w), mod_w),
                             pane(fg="gray"), max_width=mod_w)
            rx = left_x + 2 + mod_w + 1
            canvas.draw_text(rx, cy, pad_str(om.tokens_str, 8, align="right"), pane(fg="gray"), max_width=8)
            rx += 9
            canvas.draw_text(rx, cy, pad_str("—", 5, align="right"), pane(fg="gray", dim=True), max_width=5)
            rx += 6
            canvas.draw_text(rx, cy, pad_str("—", 8, align="right"), pane(fg="gray", dim=True), max_width=8)
            rx += 9
            canvas.draw_text(rx, cy, pad_str(om.cost_str, 10, align="right"), pane(fg="gray", bold=True),
                             max_width=max(0, right_x - rx))
            cy += 1

    # 5. Where the money went
    if cy + 2 < last_cy:
        canvas.draw_hline(dx + 1, cy, dw - 2, hline_ch, pane(dim=True))
        cy += 1
        canvas.draw_text(left_x, cy, t("agent_detail.where_money_went", lang), pane(bold=True), max_width=iw)
        cy += 1

        if vm.project_shares and cy < last_cy:
            segments: List[Tuple[float, Tuple[int, int, int]]] = [
                (seg.share, seg.color) for seg in vm.project_shares if seg.share > 0
            ]
            if vm.others_project_share and vm.others_project_share.share > 0:
                segments.append((vm.others_project_share.share, vm.others_project_share.color))

            bar_len = max(4, iw - 2)
            if segments:
                seg_widths = [max(1, int(round(sh * bar_len))) for sh, _ in segments]
                diff = bar_len - sum(seg_widths)
                while diff < 0:
                    widest = max(range(len(seg_widths)), key=lambda i: seg_widths[i])
                    if seg_widths[widest] <= 1:
                        break
                    seg_widths[widest] -= 1
                    diff += 1
                while diff > 0:
                    widest = max(range(len(seg_widths)), key=lambda i: seg_widths[i])
                    seg_widths[widest] += 1
                    diff -= 1

                bx = canvas.draw_text(left_x, cy, "[", pane(dim=True), max_width=1)
                for seg_w, (_, rgb) in zip(seg_widths, segments):
                    if bx >= left_x + 1 + bar_len:
                        break
                    draw_w = min(seg_w, left_x + 1 + bar_len - bx)
                    bx = canvas.draw_text(bx, cy, block_ch * draw_w, pane(fg=rgb, bold=True), max_width=draw_w)
                if bx < left_x + 1 + bar_len:
                    rem_b = left_x + 1 + bar_len - bx
                    bx = canvas.draw_text(bx, cy, " " * rem_b, pane(), max_width=rem_b)
                canvas.draw_text(left_x + 1 + bar_len, cy, "]", pane(dim=True), max_width=1)
                cy += 1

            # Legend: top 4 projects + others, wrapped across remaining lines
            if cy < last_cy:
                lx = left_x
                for _idx_l, (rgb, text) in enumerate(leg_items):
                    prefix = "" if lx == left_x else "  "
                    item_w = str_width(prefix) + str_width(leg_dot) + 1 + str_width(text)
                    if lx > left_x and lx + item_w > right_x:
                        cy += 1
                        if cy >= last_cy:
                            break
                        lx = left_x
                        prefix = ""
                    if prefix:
                        lx = canvas.draw_text(lx, cy, prefix, pane(), max_width=max(0, right_x - lx))
                    lx = canvas.draw_text(lx, cy, f"{leg_dot} ", pane(fg=rgb, bold=True), max_width=max(0, right_x - lx))
                    lx = canvas.draw_text(lx, cy, truncate_str(text, max(0, right_x - lx)),
                                          pane(fg="white"), max_width=max(0, right_x - lx))
        elif cy < last_cy:
            canvas.draw_text(left_x + 2, cy, t("agent_detail.no_project_cost", lang),
                             pane(fg="gray", dim=True), max_width=max(0, iw - 2))

    # Close note at bottom of detail pane
    close_note = t("detail.close", lang)
    canvas.draw_text(dx + max(1, (dw - str_width(close_note)) // 2), dy + dh - 2,
                     truncate_str(close_note, dw - 2), pane(dim=True))
