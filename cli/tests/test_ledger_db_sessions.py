"""A session deleted inside a SQLite store that still exists stays in the export."""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from kanjo import export
from kanjo.cache import SessionCache
from kanjo.ledger import Ledger

from tests.support import ALICE

T0 = 1793000000000


class DeletedDbSessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-dbsess-")
        self.oc = os.path.join(self.tmp, "opencode")
        os.makedirs(self.oc)
        self.data = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        self.env = mock.patch.dict(os.environ, {
            "KANJO_DATA_DIR": self.data,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_OPENCODE_DIR": self.oc,
            "KANJO_MINIMAX_DIR": os.path.join(self.tmp, "no-minimax"),
            "KANJO_TOKEI_DIR": os.path.join(self.tmp, "no-tokei"),
            "KANJO_CLAUDE_CONFIG": os.path.join(self.tmp, "no-claude.json"),
        })
        self.env.start()
        self.db = os.path.join(self.oc, "opencode.db")
        con = sqlite3.connect(self.db)
        con.executescript("""
        CREATE TABLE project(id TEXT PRIMARY KEY, worktree TEXT);
        CREATE TABLE session(id TEXT PRIMARY KEY, project_id TEXT, parent_id TEXT, directory TEXT,
                             title TEXT, time_created INTEGER, time_updated INTEGER);
        CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT);
        CREATE TABLE part(id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT);
        """)
        for i, out in ((0, 50000), (1, 100)):
            sid = "ses_%d" % i
            con.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?)",
                        (sid, None, None, self.tmp, "t%d" % i, T0 + i, T0 + i))
            con.execute("INSERT INTO message VALUES (?,?,?,?)", (
                "m%d" % i, sid, T0 + i + 5,
                json.dumps({"role": "assistant", "modelID": "claude-sonnet-4-5",
                            "tokens": {"input": 1000, "output": out, "cache": {}}})))
        con.commit()
        con.close()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.tmp)

    def export(self, use_cache):
        return export.build_export(dirs={"opencode": [self.oc]},
                                   cache=SessionCache(self.cache_dir) if use_cache else None,
                                   home=ALICE, tokei_dir=os.path.join(self.tmp, "no-tokei"))

    @staticmethod
    def ids(doc):
        found = []
        for project in doc["projects"]:
            found.extend(s["id"] for s in project["sessions_detail"])
        for name in ("unattributed", "excluded"):
            found.extend(s["id"] for s in doc["buckets"][name]["sessions_detail"])
        return sorted(found)

    def delete_session(self, sid):
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM message WHERE session_id=?", (sid,))
        con.execute("DELETE FROM session WHERE id=?", (sid,))
        con.commit()
        con.close()

    def test_deleted_session_stays_in_export(self):
        before = self.export(True)
        self.assertEqual(self.ids(before), ["ses_0", "ses_1"])
        self.delete_session("ses_0")
        for use_cache in (True, True, False, True):
            doc = self.export(use_cache)
            self.assertEqual(self.ids(doc), ["ses_0", "ses_1"])
            self.assertEqual(doc["totals"]["cost"], before["totals"]["cost"])
            self.assertEqual((doc["ledger"]["sessions"], doc["ledger"]["orphaned"]), (2, 1))
        self.assertEqual(Ledger(self.data).forget_orphans(), 1)
        self.assertEqual(self.ids(self.export(True)), ["ses_1"])

    def test_session_filtered_on_purpose_stays_excluded(self):
        self.export(True)
        with mock.patch("kanjo.sources.opencode._minimax_session_ids", return_value={"ses_0"}):
            doc = self.export(True)
        self.assertEqual(self.ids(doc), ["ses_1"])
        self.assertEqual(doc["ledger"]["orphaned"], 0)


if __name__ == "__main__":
    unittest.main()
