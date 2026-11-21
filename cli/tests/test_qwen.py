import os
import json
import shutil
import tempfile
import unittest
from unittest import mock

from kanjo.sources import qwen

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_QWEN = os.path.join(HERE, "fixtures", "qwen")


class QwenSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(qwen.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = qwen.discover([FIXTURE_QWEN])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("qwen-sess-1.jsonl", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = qwen.discover([FIXTURE_QWEN])
        self.assertEqual(len(discovered), 1)
        path = discovered[0][0]
        session = qwen.parse_file(path)

        self.assertEqual(session.id, "qwen-sess-1")
        self.assertEqual(session.agent, "qwen")
        self.assertEqual(session.cwd, "/Users/alice/Documents/GitHub/FocusApp")
        self.assertEqual(session.branch, "main")
        self.assertEqual(session.title, "Implement auth module")
        self.assertEqual(len(session.messages), 1)

        msg = session.messages[0]
        self.assertEqual(msg.model, "qwen3.8-max")
        self.assertEqual(msg.input, 700)  # 1200 - 500 cached
        self.assertEqual(msg.output, 300)
        self.assertEqual(msg.cache_read, 500)
        self.assertEqual(msg.thinking, 80)
        self.assertEqual(msg.key, "qwen:qwen-sess-1:req-qwen-1")

    def test_usage_only_sessions_and_runtime_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copytree(FIXTURE_QWEN, tmp, dirs_exist_ok=True)
            chats = os.path.join(tmp, "projects", "-Users-alice-Documents-GitHub-FocusApp", "chats")
            os.remove(os.path.join(chats, "qwen-sess-1.jsonl"))
            with open(os.path.join(chats, "qwen-sess-1.runtime.json"), "w") as handle:
                json.dump({"work_dir": "/fixture/project"}, handle)
            usage = os.path.join(tmp, "usage", "token-usage-2026-10.jsonl")
            with open(usage) as handle:
                record = json.loads(handle.readline())
            record.update(id="req-2", sessionId="qwen-sess-2")
            with open(usage, "a") as handle:
                handle.write(json.dumps(record) + "\n")
            sessions = [qwen.parse_file(path, parent) for path, parent in qwen.discover([tmp])]
            by_id = {s.id: s for s in sessions}
            self.assertEqual(set(by_id), {"qwen-sess-1", "qwen-sess-2"})
            self.assertEqual(by_id["qwen-sess-1"].cwd, "/fixture/project")
            self.assertEqual([len(s.messages) for s in by_id.values()], [1, 1])

    def test_dedupe_keys_stable(self):
        discovered = qwen.discover([FIXTURE_QWEN])
        path = discovered[0][0]
        s1 = qwen.parse_file(path)
        s2 = qwen.parse_file(path)
        self.assertEqual([m.key for m in s1.messages], [m.key for m in s2.messages])

    def test_stray_file_does_not_fall_back_to_home_qwen(self):
        tmp = tempfile.mkdtemp(prefix="kanjo-qwen-stray-")
        self.addCleanup(shutil.rmtree, tmp, True)
        stray = os.path.join(tmp, "notes.txt")
        data = os.path.join(tmp, "data")
        seen = []

        def tracking(path):
            seen.append(os.path.abspath(os.fspath(path)))
            return False

        with mock.patch.dict(os.environ, {"KANJO_DATA_DIR": data, "KANJO_QWEN_DIR": ""}), \
                mock.patch("os.path.isdir", tracking):
            root = qwen._locate_qwen_root(stray)
        self.assertEqual(os.path.abspath(root), os.path.abspath(os.path.join(data, "no-qwen")))
        self.assertNotIn(os.path.abspath(os.path.expanduser("~/.qwen")), seen)

    def test_stray_file_names_home_qwen_when_unisolated(self):
        tmp = tempfile.mkdtemp(prefix="kanjo-qwen-stray-")
        self.addCleanup(shutil.rmtree, tmp, True)
        stray = os.path.join(tmp, "notes.txt")
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("os.path.isdir", return_value=False):
            root = qwen._locate_qwen_root(stray)
        self.assertEqual(root, os.path.expanduser("~/.qwen"))


if __name__ == "__main__":
    unittest.main()
