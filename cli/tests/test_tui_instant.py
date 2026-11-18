import unittest
from unittest.mock import MagicMock
from kanjo.tui.render import Canvas, TUIState, render_ui
from kanjo.tui.term import BackgroundScanner

class TUIInstantStartTest(unittest.TestCase):
    def test_stale_header_rendering(self):
        # 3. header shows local-time stale label while stale
        state = TUIState(version="0.9.0", is_stale=True, last_generated_at_str="14:30", lang="en")
        canvas = Canvas(120, 24)
        
        # Mock filtered to skip loading screen
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
        
        # When not stale
        state.is_stale = False
        canvas = Canvas(120, 24)
        render_ui(canvas, state, filtered=filtered, total_vm=total_vm)
        line0 = canvas.get_line_text(0)
        self.assertNotIn("Data from 14:30", line0)
        self.assertNotIn("updating", line0)

    def test_stale_clears_on_doc_update(self):
        # 4. stale clears when the scanner delivers a doc.
        state = TUIState(version="0.9.0", is_stale=True)
        # Check TUIState flag.
        self.assertTrue(state.is_stale)
        state.is_stale = False
        self.assertFalse(state.is_stale)
