"""Tests for session title cleaning and parser extraction."""

import json
import os
import tempfile
import unittest

from kanjo.sources import base, claude, codex

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_CODEX_BP = os.path.join(
    HERE, "fixtures", "codex_boilerplate", "rollout-2026-08-22T00-00-00-test-boilerplate.jsonl"
)


class TitleCleanerTest(unittest.TestCase):
    def test_table_driven_cleaner(self):
        cases = [
            # Example 1 from specification:
            (
                "# Task: Full Year Heatmap fits the screen (no horizontal scrolling) Worktree: /private/tmp/claude-501/-U…",
                "Full Year Heatmap fits the screen (no horizontal scrolling)",
            ),
            # Example 2 from specification: skip metadata line and use next meaningful line
            (
                "Worktree: /private/tmp/claude-501/-Users-dogecoin-Documents-GitHub-Foc…\n# Task: Full Year Heatmap fits the screen (no horizontal scrolling)",
                "Full Year Heatmap fits the screen (no horizontal scrolling)",
            ),
            # Example 2 single line: metadata-only returns None
            (
                "Worktree: /private/tmp/claude-501/-Users-dogecoin-Documents-GitHub-Foc…",
                None,
            ),
            # Heading markers and Task: / TASK: / 任务： stripping
            ("# Task: Fix layout bug", "Fix layout bug"),
            ("## TASK: Refactor database models", "Refactor database models"),
            ("### 任务：优化移动端显示效果", "优化移动端显示效果"),
            ("任务: 修复闪退问题", "修复闪退问题"),
            ("TASK: Update dependencies", "Update dependencies"),
            ("###### Task: Deep heading test", "Deep heading test"),
            # Metadata lines dropping (Branch:, Base commit:, paths, code fences, <tags>)
            ("Branch: agy/session-titles\nReal task description here", "Real task description here"),
            ("Base commit: abc123def456\nAnother task description", "Another task description"),
            ("```python\nprint('hello world')\n```\nUser prompt following code fence", "User prompt following code fence"),
            ("<environment_context>\n<cwd>/Users/alice</cwd>\n</environment_context>\nActual task", "Actual task"),
            ("<tags>\n<command_output>ignored</command_output>\n</tags>", None),
            # Never return a title that is only a path
            ("/private/tmp/claude-501/-Users-dogecoin-Documents-GitHub-FocusApp", None),
            ("~/Documents/GitHub/FocusApp", None),
            ("https://github.com/mammut001/FocusApp", None),
            ("./scripts/build.sh", None),
            # Whitespace collapsing
            ("  Fix    the    ledger    bug  ", "Fix the ledger bug"),
            ("\t\tTabs\tand   multiple   spaces\t\t", "Tabs and multiple spaces"),
            # Sentence end cutting (English)
            ("Fix the crash on launch. Make sure tests pass.", "Fix the crash on launch."),
            ("Can we update the color theme? Dark mode looks much better.", "Can we update the color theme?"),
            ("Important notice! Do not touch production database.", "Important notice!"),
            # Sentence end cutting (CJK)
            ("这是一段中文测试内容。后面还有更多说明内容。", "这是一段中文测试内容。"),
            ("这个组件可以改动吗？请确认一下需求细节。", "这个组件可以改动吗？"),
            ("注意！不要删除生产数据。", "注意！"),
            # Truncation at ~80 chars on word/character boundary (CJK-aware) with '…'
            (
                "This is a very long task description without any sentence terminator that keeps on going and going until it exceeds eighty characters",
                "This is a very long task description without any sentence terminator that keeps…",
            ),
            (
                "这是一个非常长的任务描述没有任何句子标点符号一直写下去一直写下去一直写下去一直写下去一直写下去直到超过八十个字符为了测试中文字符边界切割功能是否能够正常工作另外再增加一些内容确保长度确实超过八十个字符",
                "这是一个非常长的任务描述没有任何句子标点符号一直写下去一直写下去一直写下去一直写下去一直写下去直到超过八十个字符为了测试中文字符边界切割功能是否能够正常工作另…",
            ),
            # Pasted text in Codex desktop format
            (
                '# Files pasted by the user:\n\n## "Continue ONLY on PR #85. Repository: https://github.com/mammut001/FocusApp PR: …": /Users/alice/.codex/attachments/pasted-text.txt',
                "Continue ONLY on PR #85.",
            ),
            # Realtime delegation input extraction
            (
                "<realtime_delegation>\n  <input>我可能已经记不得它,最后的几秒钟。会不会带走啊?</input>\n  <transcript_delta>hello</transcript_delta>\n</realtime_delegation>",
                "我可能已经记不得它,最后的几秒钟。",
            ),
            # Flush tail notification is ignored
            (
                "<realtime_delegation>\n  <source>transcript_tail_flush</source>\n  <input>The user just ended their realtime session.</input>\n</realtime_delegation>",
                None,
            ),
            # Empty / non-string inputs
            ("", None),
            ("   \n   \t  ", None),
            (None, None),
            (12345, None),
        ]
        for inp, expected in cases:
            with self.subTest(input=inp):
                res = base.clean_title(inp)
                self.assertEqual(res, expected)
                self.assertEqual(base.short_title(inp), expected)
                if res is not None:
                    self.assertLessEqual(len(res), 80)


class ClaudeSessionTitleTest(unittest.TestCase):
    def test_compaction_preamble_summary_extraction(self):
        text = (
            "This session is being continued from a previous conversation that ran out of context. "
            "The summary below covers the earlier portion of the conversation.\n\n"
            "Summary:\n"
            "1. Primary Request and Intent:\n"
            "   - **Active /goal (Stop hook)**: «我同意，还在改吗你来做吧 都弄吧，可以用agy supervisor来做然后你来验证。都弄吧全部开始» — enrich the Échelle"
        )
        cleaned = base.clean_title(text)
        self.assertEqual(cleaned, "我同意，还在改吗你来做吧 都弄吧，可以用agy supervisor来做然后你来验证。")

    def test_claude_parser_custom_title_takes_precedence(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "custom-title", "customTitle": "App Store 上线规划"}) + "\n")
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2026-10-20T10:00:00.000Z",
                "message": {"content": "This session is being continued from a previous conversation that ran out of context."}
            }) + "\n")
            path = f.name
        try:
            s = claude.parse_file(path)
            self.assertEqual(s.title, "App Store 上线规划")
        finally:
            os.remove(path)

    def test_claude_parser_compaction_fallback_to_next_real_prompt(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            # Compaction preamble with no summary content
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2026-10-20T10:00:00.000Z",
                "message": {"content": "This session is being continued from a previous conversation that ran out of context."}
            }) + "\n")
            # Next real user prompt
            f.write(json.dumps({
                "type": "user",
                "timestamp": "2026-10-20T10:01:00.000Z",
                "message": {"content": "# Task: Fix payment webhook authentication\nWorktree: /tmp/wt"}
            }) + "\n")
            path = f.name
        try:
            s = claude.parse_file(path)
            self.assertEqual(s.title, "Fix payment webhook authentication")
        finally:
            os.remove(path)


class CodexBoilerplateFixtureTest(unittest.TestCase):
    def test_codex_fixture_with_boilerplate(self):
        self.assertTrue(os.path.isfile(FIXTURE_CODEX_BP), "Fixture file must exist")
        session = codex.parse_file(FIXTURE_CODEX_BP)
        self.assertEqual(session.id, "codex-boilerplate-1")
        self.assertEqual(session.agent, "codex")
        self.assertEqual(session.title, "Implement dashboard widgets for iOS app")
        self.assertEqual(len(session.messages), 1)


if __name__ == "__main__":
    unittest.main()
