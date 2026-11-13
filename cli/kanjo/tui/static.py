"""Static mode rendering (Canvas -> ANSI string or plain text)."""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Optional
from datetime import datetime

from .model import (
    FilteredData, TimeRange, ViewMode, build_agent_rows, build_antigravity_accounts_section,
    build_day_rows, build_model_rows, build_project_footer_rows, build_project_rows,
    build_subscription_meters, build_total_view_model, ensure_aware, filter_report, get_tz
)
from .render import Canvas, Style, TUIState, render_ui, str_width

NAMED_FG = {
    "black": 30, "red": 31, "green": 32, "yellow": 33,
    "blue": 34, "magenta": 35, "cyan": 36, "white": 37,
    "gray": 90, "grey": 90,
}

NAMED_BG = {
    "black": 40, "red": 41, "green": 42, "yellow": 43,
    "blue": 44, "magenta": 45, "cyan": 46, "white": 47,
    "gray": 100, "grey": 100,
}


def rgb_to_256(r: int, g: int, b: int) -> int:
    def to_cube(v: int) -> int:
        if v < 48:
            return 0
        if v < 115:
            return 1
        return min(5, (v - 35) // 40)
    return 16 + 36 * to_cube(r) + 6 * to_cube(g) + to_cube(b)


def style_to_ansi(style: Style, truecolor: bool = True) -> str:
    parts = []
    if style.bold:
        parts.append("1")
    if style.dim:
        parts.append("2")
    if style.underline:
        parts.append("4")
    if style.inverse:
        parts.append("7")

    # Foreground
    if style.fg:
        if isinstance(style.fg, tuple) and len(style.fg) == 3:
            r, g, b = style.fg
            if truecolor:
                parts.append(f"38;2;{r};{g};{b}")
            else:
                parts.append(f"38;5;{rgb_to_256(r, g, b)}")
        elif isinstance(style.fg, str) and style.fg in NAMED_FG:
            parts.append(str(NAMED_FG[style.fg]))
        elif isinstance(style.fg, int):
            parts.append(f"38;5;{style.fg}")

    # Background
    if style.bg:
        if isinstance(style.bg, tuple) and len(style.bg) == 3:
            r, g, b = style.bg
            if truecolor:
                parts.append(f"48;2;{r};{g};{b}")
            else:
                parts.append(f"48;5;{rgb_to_256(r, g, b)}")
        elif isinstance(style.bg, str) and style.bg in NAMED_BG:
            parts.append(str(NAMED_BG[style.bg]))
        elif isinstance(style.bg, int):
            parts.append(f"48;5;{style.bg}")

    if not parts:
        return ""
    return f"\033[{';'.join(parts)}m"


def canvas_to_ansi(canvas: Canvas, no_color: bool = False, truecolor: bool = True) -> str:
    """Convert a Canvas to an ANSI string or plain text."""
    lines = []
    reset = "\033[0m"

    for y in range(canvas.height):
        row = canvas.get_line_cells(y)
        if no_color:
            # Plain text
            line_str = "".join(cell.char for cell in row).rstrip()
            lines.append(line_str)
            continue

        # Color mode
        line_parts = []
        cur_style = Style()
        style_open = False

        for cell in row:
            if cell.style != cur_style:
                if style_open:
                    line_parts.append(reset)
                    style_open = False
                cur_style = cell.style
                seq = style_to_ansi(cur_style, truecolor=truecolor)
                if seq:
                    line_parts.append(seq)
                    style_open = True
            line_parts.append(cell.char)

        if style_open:
            line_parts.append(reset)

        lines.append("".join(line_parts).rstrip())

    # Drop trailing empty lines
    while lines and not lines[-1].strip():
        lines.pop()

    return "\n".join(lines) + "\n"


def is_truecolor_supported() -> bool:
    colorterm = os.environ.get("COLORTERM", "").lower()
    return colorterm in ("truecolor", "24bit")


def render_static_snapshot(
    doc: dict,
    width: int = 80,
    height: Optional[int] = None,
    no_color: bool = False,
    ascii_mode: bool = False,
    now: Optional[datetime] = None,
    time_range: TimeRange = TimeRange.ALL,
    view_mode: ViewMode = ViewMode.PROJECTS,
    version: str = "0.9.0",
    antigravity_accounts_data: Optional[Any] = None,
    current_account: Optional[str] = None
) -> str:
    """Produce one static snapshot of the UI."""
    doc = doc or {}
    tz = get_tz(doc)
    now = ensure_aware(now, tz) or datetime.now(tz)

    filtered = filter_report(doc, time_range, now=now)
    total_vm = build_total_view_model(filtered)
    meters = build_subscription_meters(doc, now=now)
    accounts_section = build_antigravity_accounts_section(
        doc, now=now, antigravity_data=antigravity_accounts_data, current_account=current_account
    )
    proj_rows = build_project_rows(filtered, now, tz, ascii_mode=ascii_mode)
    proj_footers = build_project_footer_rows(filtered, now, tz, ascii_mode=ascii_mode)
    model_rows = build_model_rows(filtered)
    agent_rows = build_agent_rows(filtered)
    day_rows = build_day_rows(filtered)

    # Estimate required height if not specified
    if height is None:
        needed = 4  # header + total + share bar + spacing
        if meters:
            for m in meters:
                needed += 1 + len(m.windows)
        if accounts_section:
            needed += 1 + len(accounts_section.rows)
        needed += 1  # divider
        needed += 1  # table header
        if view_mode == ViewMode.PROJECTS:
            needed += min(15, len(proj_rows))
            needed += len(proj_footers)
        elif view_mode == ViewMode.MODELS:
            needed += min(15, len(model_rows))
        elif view_mode == ViewMode.AGENTS:
            needed += min(15, len(agent_rows))
        elif view_mode == ViewMode.DAYS:
            needed += min(15, len(day_rows))
        needed += 2  # F-key bar + margin
        height = max(24, needed)

    canvas = Canvas(width, height)
    state = TUIState(
        version=version,
        time_range=time_range,
        view_mode=view_mode,
        ascii_mode=ascii_mode,
        no_color=no_color,
        last_refresh_time=now.strftime("%H:%M:%S"),
    )

    render_ui(
        canvas=canvas,
        state=state,
        filtered=filtered,
        total_vm=total_vm,
        meters=meters,
        accounts_section=accounts_section,
        project_rows=proj_rows,
        project_footers=proj_footers,
        model_rows=model_rows,
        agent_rows=agent_rows,
        day_rows=day_rows,
        static_mode=True,
    )

    tc = is_truecolor_supported() and not no_color
    return canvas_to_ansi(canvas, no_color=no_color, truecolor=tc)
