"""Tests for session title cleaning and parser extraction."""

import json
import os
import tempfile
import unittest

from kanjo.sources import base, claude, codex, commandcode

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
            # Lead-in line ending with ':' that has < 6 words
            ("You are working in:\n# Task: Add export filtering", "Add export filtering"),
            ("You are working in:", None),
            ("Repository:\nhttps://github.com/alice/repo\nImplement feature X", "Implement feature X"),
            ("My request:\nDo something useful", "Do something useful"),
            # Lines whose main content is a filesystem path or starting with Work only / Only modify / You are working
            (
                "Work ONLY /Users/dogecoin/Documents/GitHub/reussir-en-francais\nImplement French quiz module",
                "Implement French quiz module",
            ),
            ("Work ONLY /Users/dogecoin/Documents/GitHub/reussir-en-francais", None),
            ("Only modify /private/tmp/wt", None),
            ("You are working locally on the mammut001/FocusApp repository:", None),
            ("In /Users/alice/repo:", None),
            # Git raw/diff lines
            (
                ":100644 100644 269f21f 4a3c38d M capture-your-screen/main.swift\nReview screen recording diff",
                "Review screen recording diff",
            ),
            (":100644 100644 269f21f 4a3c38d M capture-your-screen/main.swift", None),
            ("diff --git a/foo.py b/foo.py\nFix syntax error in foo", "Fix syntax error in foo"),
            # JSON-only or mostly punctuation
            ('{"page_id":null}\nActual user prompt here', "Actual user prompt here"),
            ('{"page_id":null}', None),
            ('[{"key": "value"}]', None),
            ("--- === ***", None),
            ("[]", None),
            # Slash-command-only messages
            ("/taste off", None),
            ("/taste off\nStart new feature", "Start new feature"),
            ("/compact", None),
            ("/goal", None),
            ("/goal Fix navigation animation", "Fix navigation animation"),
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

    def test_codex_skips_json_only_first_message(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({
                "timestamp": "2026-08-22T00:00:00.000Z",
                "type": "session_meta",
                "payload": {"id": "codex-json-1", "session_id": "codex-json-1"}
            }) + "\n")
            f.write(json.dumps({
                "timestamp": "2026-08-22T00:00:01.000Z",
                "type": "turn_context",
                "payload": {"cwd": "/Users/alice/repo", "model": "gpt-5.5"}
            }) + "\n")
            # Message 1: JSON-only
            f.write(json.dumps({
                "timestamp": "2026-08-22T00:00:02.000Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": '{"page_id":null}'}
            }) + "\n")
            # Message 2: Real prompt
            f.write(json.dumps({
                "timestamp": "2026-08-22T00:00:03.000Z",
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Refactor authentication flow"}
            }) + "\n")
            path = f.name
        try:
            s = codex.parse_file(path)
            self.assertEqual(s.title, "Refactor authentication flow")
        finally:
            os.remove(path)


class CommandCodeFallbackTest(unittest.TestCase):
    def test_slash_command_fallback_to_next_message(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "session", "id": "cmd-test-1", "cwd": "/Users/alice/repo"}) + "\n")
            # Message 1: slash command only
            f.write(json.dumps({
                "type": "message",
                "timestamp": "2026-10-20T10:00:00.000Z",
                "message": {"role": "user", "content": "/taste off"}
            }) + "\n")
            # Message 2: real prompt
            f.write(json.dumps({
                "type": "message",
                "timestamp": "2026-10-20T10:01:00.000Z",
                "message": {"role": "user", "content": "Fix button styling in settings"}
            }) + "\n")
            path = f.name
        try:
            s = commandcode.parse_file(path)
            self.assertEqual(s.title, "Fix button styling in settings")
        finally:
            os.remove(path)

    def test_slash_command_only_falls_back_to_none(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(json.dumps({"type": "session", "id": "cmd-test-2", "cwd": "/Users/alice/repo"}) + "\n")
            f.write(json.dumps({
                "type": "message",
                "timestamp": "2026-10-20T10:00:00.000Z",
                "message": {"role": "user", "content": "/taste off"}
            }) + "\n")
            path = f.name
        try:
            s = commandcode.parse_file(path)
            self.assertIsNone(s.title)
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
