"""Tests for instant startup with stale cached export in `kanjo usage`."""

try:
    import curses
except ImportError:
    curses = None
from datetime import datetime, timezone
import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from kanjo import cli
from kanjo.config import Config
from kanjo.tui.model import format_month_day_time, get_tz, parse_iso_dt
from kanjo.tui.render import Canvas, TUIState, render_ui
from kanjo.tui.term import HAVE_CURSES, run_curses_tui


class FakeStdscr:
    """Mock curses stdscr for headless testing."""

    def __init__(self, width: int = 120, height: int = 24, keys=None, on_getch=None):
        self.w = width
        self.h = height
        self.keys = list(keys or [ord("q")])
        self.on_getch = on_getch
        self.captured = []
        self.frames = [0]
        self.getch_calls = 0

    def getmaxyx(self):
        return (self.h, self.w)

    def timeout(self, ms):
        pass

    def keypad(self, flag):
        pass

    def erase(self):
        self.frames.append(len(self.captured))

    def addstr(self, *args):
        self.captured.append(args)

    def insch(self, *args):
        pass

    def noutrefresh(self):
        pass

    def getch(self):
        self.getch_calls += 1
        if self.on_getch is not None:
            self.on_getch(self.getch_calls)
        if self.keys:
            return self.keys.pop(0)
        return ord("q")


def screen_frames(scr):
    """Text of every frame a fake stdscr drew, oldest first."""
    bounds = list(getattr(scr, "frames", None) or [0]) + [len(scr.captured)]
    texts = []
    for start, end in zip(bounds, bounds[1:]):
        grid = {}
        for call in scr.captured[start:end]:
            if len(call) < 3:
                continue
            y, x, text = call[0], call[1], call[2]
            for offset, ch in enumerate(text):
                grid[(y, x + offset)] = ch
        if not grid:
            continue
        width = max(x for _y, x in grid) + 1
        height = max(y for y, _x in grid) + 1
        texts.append(
            "\n".join(
                "".join(grid.get((y, x), " ") for x in range(width)).rstrip()
                for y in range(height)
            )
        )
    return texts


class TUIInstantStartTest(unittest.TestCase):
    def test_stale_header_rendering(self):
        state = TUIState(version="0.9.0", is_stale=True, last_generated_at_str="14:30", lang="en")
        canvas = Canvas(120, 24)

        filtered = MagicMock()
        total_vm = MagicMock()
        total_vm.cost_str = "$0.00"
        total_vm.tokens_str = "0"
        total_vm.sessions_str = "0"
        total_vm.projects_str = "0"

        render_ui(canvas, state, filtered=filtered, total_vm=total_vm)

        line0 = canvas.get_line_text(0)
        self.assertIn("Data from 14:30", line0)
        self.assertIn("updating", line0)

        state.is_stale = False
        canvas = Canvas(120, 24)
        render_ui(canvas, state, filtered=filtered, total_vm=total_vm)
        line0 = canvas.get_line_text(0)
        self.assertNotIn("Data from 14:30", line0)
        self.assertNotIn("updating", line0)

    def test_stale_time_string_format(self):
        doc = {"generated_at": "2026-11-17T19:30:00Z", "timezone": "America/Toronto"}
        tz = get_tz(doc)
        dt = parse_iso_dt(doc["generated_at"], default_tz=tz)
        self.assertIsNotNone(dt)

        formatted = format_month_day_time(dt, tz, lang="en", now=dt)
        self.assertIn("14:30", formatted)
        self.assertNotIn("19:30", formatted)

    @unittest.skipIf(not HAVE_CURSES or curses is None, "requires curses")
    def test_cmd_usage_fallback_logic(self):
        full_doc = {
            "generated_at": "2026-11-17T19:30:00Z",
            "timezone": "America/Toronto",
            "projects": [],
            "totals": {"cost": 0.0, "tokens": 0, "sessions": 0},
        }
        partial_doc = {
            "generated_at": "2026-11-17T19:30:00Z",
            "totals": {"cost": 0.0, "tokens": 0, "sessions": 0},
        }

        captured = []

        def fake_wrapper(func, *args, **kwargs):
            captured.append((func, kwargs))
            return 0

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "export-last.json")
            env_patch = {
                "KANJO_CACHE_DIR": tmpdir,
                "KANJO_CONFIG_DIR": tmpdir,
                "KANJO_DATA_DIR": tmpdir,
            }
            with patch.dict(os.environ, env_patch), \
                 patch("kanjo.cli.load_config", return_value=Config()), \
                 patch("kanjo.cli.source_fingerprint", return_value="matching-fp"), \
                 patch.object(cli.sys.stdout, "isatty", return_value=True), \
                 patch("curses.wrapper", side_effect=fake_wrapper):

                # 1. Fingerprint miss + full doc -> initial_doc=full_doc, is_stale=True
                with open(cache_path, "w", encoding="utf-8") as handle:
                    json.dump(
                        {"fingerprint": "old-fp", "scanned_at": time.time() - 600, "doc": full_doc},
                        handle,
                    )
                rc = cli.main(["usage"])
                self.assertEqual(rc, 0)
                self.assertEqual(captured[-1][0], run_curses_tui)
                self.assertEqual(captured[-1][1]["initial_doc"], full_doc)
                self.assertTrue(captured[-1][1]["is_stale"])

                # 2. Fingerprint miss + non-full doc (no 'projects') -> initial_doc=None, is_stale=False
                with open(cache_path, "w", encoding="utf-8") as handle:
                    json.dump(
                        {"fingerprint": "old-fp", "scanned_at": time.time() - 600, "doc": partial_doc},
                        handle,
                    )
                rc = cli.main(["usage"])
                self.assertEqual(rc, 0)
                self.assertIsNone(captured[-1][1]["initial_doc"])
                self.assertFalse(captured[-1][1]["is_stale"])

                # 3. Matching fingerprint + full doc -> initial_doc=full_doc, is_stale=False
                with open(cache_path, "w", encoding="utf-8") as handle:
                    json.dump(
                        {"fingerprint": "matching-fp", "scanned_at": time.time() - 600, "doc": full_doc},
                        handle,
                    )
                rc = cli.main(["usage"])
                self.assertEqual(rc, 0)
                self.assertEqual(captured[-1][1]["initial_doc"], full_doc)
                self.assertFalse(captured[-1][1]["is_stale"])

    @unittest.skipIf(not HAVE_CURSES or curses is None, "requires curses")
    def test_run_curses_tui_doc_swap_regression(self):
        stale_doc = {
            "generated_at": "2026-11-17T19:30:00Z",
            "timezone": "America/Toronto",
            "projects": [
                {
                    "name": "stale-proj",
                    "cost": 1.25,
                    "tokens": 1000,
                    "sessions": 1,
                    "by_day": [],
                    "by_agent": [],
                }
            ],
            "totals": {"cost": 1.25, "tokens": 1000, "sessions": 1},
        }
        fresh_doc = {
            "generated_at": "2026-11-18T00:15:00Z",
            "timezone": "America/Toronto",
            "projects": [
                {
                    "name": "fresh-proj",
                    "cost": 2.50,
                    "tokens": 2000,
                    "sessions": 2,
                    "by_day": [],
                    "by_agent": [],
                }
            ],
            "totals": {"cost": 2.50, "tokens": 2000, "sessions": 2},
        }

        created_scanners = []

        class FakeScanner:
            def __init__(self, *args, **kwargs):
                self._lock = threading.Lock()
                self.latest_doc = None
                self.doc_version = 0
                self.is_scanning = False
                self.last_scan_time = ""
                self.antigravity_accounts_data = None
                self.current_account = None
                self.last_error = None
                self.error_seq = 0
                created_scanners.append(self)

            def start(self):
                pass

            def stop(self):
                pass

            def refresh_now(self):
                pass

        def on_getch(call_num):
            if call_num == 1:
                scanner = created_scanners[0]
                with scanner._lock:
                    scanner.latest_doc = fresh_doc
                    scanner.doc_version = 1
                    scanner.last_scan_time = "19:15:00"
                    scanner.is_scanning = False

        scr = FakeStdscr(width=120, height=24, keys=[-1, ord("q")], on_getch=on_getch)

        with patch("kanjo.tui.term.BackgroundScanner", FakeScanner):
            rc = run_curses_tui(
                scr,
                initial_doc=stale_doc,
                no_color=True,
                mouse=False,
                lang="en",
                is_stale=True,
            )

        self.assertEqual(rc, 0)
        frames = screen_frames(scr)
        self.assertGreaterEqual(len(frames), 2)

        # First frame: stale initial doc shows local time (14:30) stale header and stale project
        first_header = frames[0].splitlines()[0]
        self.assertIn("Data from", first_header)
        self.assertIn("14:30", first_header)
        self.assertNotIn("19:30", first_header)
        self.assertIn("stale-proj", frames[0])

        # Final frame: after scanner delivers fresh doc, stale label is gone and fresh project appears
        last_header = frames[-1].splitlines()[0]
        self.assertNotIn("Data from", last_header)
        self.assertIn("19:15:00", last_header)
        self.assertIn("fresh-proj", frames[-1])
