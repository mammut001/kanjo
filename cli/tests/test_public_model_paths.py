"""Path-like model ids never leak a username or local path into shared outputs."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

FAMILY_SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "family-server"))
if FAMILY_SERVER_DIR not in sys.path:
    sys.path.insert(0, FAMILY_SERVER_DIR)

from family_server.validation import check_privacy_backstop

from kanjo import export
from kanjo.config import Config
from kanjo.sources.base import Message, Session

MODELS = [
    "/Users/alice/models/Qwen3-Coder-30B-Q4_K_M.gguf",
    "/home/bob/llm/qwen.gguf",
    "C:\\Users\\carol\\models\\q.gguf",
    "~/models/local-model.safetensors",
]


def _sessions():
    out = []
    for i, model in enumerate(MODELS):
        s = Session(id="s%d" % i, agent="opencode", file="/x/%d" % i)
        s.messages.append(Message(ts=1793000000.0 + i, model=model, input=100, output=10, key="k%d" % i))
        out.append(s)
    return out


class PublicModelPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-model-paths-")
        self.env = mock.patch.dict(os.environ, {
            "KANJO_DATA_DIR": os.path.join(self.tmp, "data"),
            "KANJO_CACHE_DIR": os.path.join(self.tmp, "cache"),
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def assert_clean(self, doc):
        text = json.dumps(doc)
        for needle in ("Users", "home/", "alice", "bob", "carol", "\\\\", ".gguf", "~"):
            self.assertNotIn(needle, text)

    def test_public_summary_and_family_report(self):
        result = export.ScanResult(sessions=_sessions(), failed_files=[], stats={})
        doc = export.build_public_summary(config=Config(), scan_result=result, home=self.tmp)
        self.assert_clean(doc)
        self.assertIn("Qwen3-Coder-30B-Q4_K_M", doc["all_time"]["models_used"])
        result = export.ScanResult(sessions=_sessions(), failed_files=[], stats={})
        with mock.patch("kanjo.quota.quota_windows", return_value={}):
            report = export.build_family_report(config=Config(family_agents="all"), scan_result=result,
                                                home=self.tmp, tokei_dir=os.path.join(self.tmp, "tokei"))
        self.assert_clean(report["summary"])
        self.assertIn("local-model", report["summary"]["all_time"]["models_used"])

    def test_ordinary_ids_unchanged(self):
        prices = export.default_book()
        self.assertEqual(export._public_model_name("openrouter/qwen/qwen3-max", "opencode", prices), "qwen/qwen3-max")
        self.assertEqual(export._public_model_name("my-local-model-high", "opencode", prices), "my-local-model")

    def test_server_backstop_rejects_relative_and_windows_paths(self):
        for value in ("Users/alice/models/x.gguf", "C:\\Users\\carol\\q.gguf", "home/bob/x"):
            body = json.dumps({"model": value}).encode("utf-8")
            self.assertIsNotNone(check_privacy_backstop(body), value)
        self.assertIsNone(check_privacy_backstop(json.dumps({"model": "qwen/qwen3-max"}).encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
