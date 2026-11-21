import unittest

from kanjo.export import dedupe
from kanjo.sources.base import Message, Session


class DedupeScopesTest(unittest.TestCase):
    def test_message_ids_are_scoped_to_agent_and_subagent_file(self):
        def make(sid, agent, parent=None):
            return Session(id=sid, agent=agent, file=sid, subagent_of=parent,
                           messages=[Message(ts=1, model="unknown", input=1, key="shared")])

        sessions = [make("parent", "claude"), make("fork", "claude"),
                    make("child", "claude", "parent"),
                    make("child2", "claude", "parent"), make("other", "codex")]
        result = dedupe(sessions)
        counts = {s.id: len(s.messages) for s in result}
        self.assertEqual(counts, {"parent": 0, "fork": 1, "child": 1,
                                  "child2": 1, "other": 1})
