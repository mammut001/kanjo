"""Grok print-mode sessions: the exported start time is the session's creation time."""

import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from kanjo import export
from kanjo.sources.base import Message, Session


def _ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


class GrokSessionStartTests(unittest.TestCase):
    def _detail(self, agent, origin, turn_end):
        msg = Message(ts=_ts(turn_end), model="grok-4.6", input=100, output=10, key=agent + ":s1:1")
        s = Session(id="s1", agent=agent, file="/tmp/s1", cwd="/tmp/no-repo-here", messages=[msg],
                    origin_ts=_ts(origin))
        s.note_time(s.origin_ts)
        s.note_time(msg.ts)
        scan = export.ScanResult(sessions=[s], failed_files=[], stats={})
        with mock.patch.dict(os.environ, {"TZ": "UTC", "KANJO_NO_NETWORK": "1"}):
            doc = export.build_export(scan_result=scan, now=datetime(2026, 11, 19, tzinfo=timezone.utc))
        details = [d for p in doc["projects"] + list(doc["buckets"].values()) for d in p.get("sessions_detail", [])]
        self.assertEqual(len(details), 1)
        return details[0]

    def test_single_turn_grok_session_starts_at_created_at(self):
        d = self._detail("grok", "2026-11-18T23:49:18Z", "2026-11-18T23:55:33Z")
        self.assertEqual(d["started"], "2026-11-18T23:49:18Z")
        self.assertEqual(d["ended"], "2026-11-18T23:55:33Z")

    def test_other_agents_keep_first_message_time(self):
        d = self._detail("codex", "2026-11-18T23:49:18Z", "2026-11-18T23:55:33Z")
        self.assertEqual(d["started"], "2026-11-18T23:55:33Z")


if __name__ == "__main__":
    unittest.main()
