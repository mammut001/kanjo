import os
import json
import shutil
import tempfile
import unittest

from kanjo.pricing import default_book
from kanjo.sources import qwenwork

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE_QWENWORK = os.path.join(HERE, "fixtures", "qwenwork", "logs", "sessions")


class QwenWorkSourceTest(unittest.TestCase):
    def test_missing_dir_yields_zero_sessions(self):
        self.assertEqual(qwenwork.discover(["/nonexistent/directory/that/does/not/exist"]), [])

    def test_discover_fixture(self):
        discovered = qwenwork.discover([FIXTURE_QWENWORK])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        self.assertIn("qw-sess-uuid-1", path)
        self.assertIsNone(parent)

    def test_parse_session(self):
        discovered = qwenwork.discover([FIXTURE_QWENWORK])
        self.assertEqual(len(discovered), 1)
        path, parent = discovered[0]
        session = qwenwork.parse_file(path, parent)

        self.assertEqual(session.id, "qw-sess-uuid-1")
        self.assertEqual(session.agent, "qwenwork")
        self.assertEqual(session.cwd, "/Users/alice/Projects/demo")
        self.assertEqual(session.title, "Refactor authentication flow")
        # req-1 has duplicate response completed event, so total messages should be 2, not 3
        self.assertEqual(len(session.messages), 2)

        # Message 1
        msg1 = session.messages[0]
        self.assertEqual(msg1.model, "qwork-advanced")
        # In fixture: input_tokens=1500, cache_read_input_tokens=500 -> non-cached input = 1000
        self.assertEqual(msg1.input, 1000)
        self.assertEqual(msg1.output, 300)
        self.assertEqual(msg1.cache_read, 500)
        self.assertEqual(msg1.cache_write, 0)
        self.assertEqual(msg1.key, "qwenwork:qw-sess-uuid-1:req-1")

        # Message 2 (from second segment file in sequence)
        msg2 = session.messages[1]
        self.assertEqual(msg2.model, "qmodel_latest")
        # In fixture: input_tokens=2000, cache_creation_input_tokens=200 -> non-cached input = 1800
        self.assertEqual(msg2.input, 1800)
        self.assertEqual(msg2.output, 400)
        self.assertEqual(msg2.cache_read, 0)
        self.assertEqual(msg2.cache_write, 200)
        self.assertEqual(msg2.key, "qwenwork:qw-sess-uuid-1:req-2")

        # Tool paths
        self.assertEqual(
            session.tool_paths,
            [
                ["/Users/alice/Projects/demo/auth.py"],
                ["/Users/alice/Projects/demo/utils.py"],
            ],
        )

    def test_malformed_response_does_not_hide_valid_requests(self):
        session_dir = qwenwork.discover([FIXTURE_QWENWORK])[0][0]
        with tempfile.TemporaryDirectory() as tmp:
            copy = os.path.join(tmp, "session")
            shutil.copytree(session_dir, copy)
            segment = os.path.join(copy, "segments", "0000000001.jsonl")
            with open(segment) as handle:
                lines = handle.readlines()
            bad = json.loads(lines[-2])
            bad["data"]["input_tokens"] = "invalid"
            with open(segment, "w") as handle:
                handle.write(json.dumps(bad) + "\n")
                handle.writelines(lines)
            session = qwenwork.parse_file(copy)
        self.assertEqual([m.input for m in session.messages], [1000, 1800])

    def test_no_double_counting_total_prompt_tokens(self):
        discovered = qwenwork.discover([FIXTURE_QWENWORK])
        session = qwenwork.parse_file(discovered[0][0])
        msg1 = session.messages[0]
        # Raw event had input_tokens=1500, cache_read_input_tokens=500.
        # Ensure input + cache_read == 1500, not 1500 + 500 = 2000.
        self.assertEqual(msg1.input + msg1.cache_read, 1500)

    def test_cost_and_pricing_resolution(self):
        discovered = qwenwork.discover([FIXTURE_QWENWORK])
        session = qwenwork.parse_file(discovered[0][0])
        book = default_book()

        # Both qwork-advanced and qmodel_latest should resolve without estimation
        for msg in session.messages:
            cost, estimated = book.cost(
                msg.model,
                session.agent,
                input_tokens=msg.input,
                output_tokens=msg.output,
                cache_read=msg.cache_read,
                cache_write=msg.cache_write,
            )
            self.assertGreater(cost, 0.0)
            self.assertFalse(estimated, f"Model {msg.model} should not be estimated")

    def test_parse_cache_sees_growing_segments(self):
        from kanjo.cache import SessionCache

        def event(n):
            return json.dumps({
                "type": "model.response.completed", "ts": "2026-11-09T10:00:%02dZ" % n,
                "request_id": "req-%d" % n,
                "data": {"model": "qwork-advanced", "input_tokens": 10, "output_tokens": 5},
            }) + "\n"

        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = os.path.join(tmp, "cache")
            session_dir = os.path.join(tmp, "sessions", "-enc", "sess-1")
            seg_dir = os.path.join(session_dir, "segments")
            os.makedirs(seg_dir)
            seg1 = os.path.join(seg_dir, "0000000001.jsonl")
            with open(seg1, "w") as handle:
                handle.write(event(1))
            path, parent = qwenwork.discover([os.path.join(tmp, "sessions")])[0]

            def cached_count():
                cache = SessionCache(cache_dir)
                session = cache.get("qwenwork", path, parent, qwenwork.parse_file)
                cache.save()
                return len(session.messages)

            self.assertEqual(cached_count(), 1)
            with open(seg1, "a") as handle:
                handle.write(event(2))
            self.assertEqual(cached_count(), 2)
            with open(os.path.join(seg_dir, "0000000002.jsonl"), "w") as handle:
                handle.write(event(3))
            self.assertEqual(cached_count(), 3)

    def test_env_roots(self):
        old_env = os.environ.get("KANJO_QWENWORK_DIR")
        try:
            os.environ["KANJO_QWENWORK_DIR"] = FIXTURE_QWENWORK
            roots = qwenwork.roots()
            self.assertEqual(roots, [FIXTURE_QWENWORK])
        finally:
            if old_env is not None:
                os.environ["KANJO_QWENWORK_DIR"] = old_env
            else:
                os.environ.pop("KANJO_QWENWORK_DIR", None)


if __name__ == "__main__":
    unittest.main()
