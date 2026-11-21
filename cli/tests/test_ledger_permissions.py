"""The permanent ledger holds prompt titles and paths: only the owner may read it."""
import os
import stat
import tempfile
import unittest

from kanjo.ledger import Ledger
from kanjo.sources.base import Message, Session


def _session(sid):
    s = Session(id=sid, agent="claude", file="/x/%s.jsonl" % sid)
    s.title = "secret first prompt"
    s.messages.append(Message(ts=1793000000.0, model="claude-opus-4-5", input=10, output=5, key="k-" + sid))
    return s


@unittest.skipIf(os.name == "nt", "POSIX permissions")
class LedgerPermissionsTest(unittest.TestCase):
    def setUp(self):
        self.old = os.umask(0o022)

    def tearDown(self):
        os.umask(self.old)

    def mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_full_save_and_journal_are_owner_only(self):
        with tempfile.TemporaryDirectory() as root:
            directory = os.path.join(root, "share", "kanjo")
            ledger = Ledger(directory)
            ledger.note_file(_session("a"), os.path.join(root, "a.jsonl"))
            ledger.save()
            self.assertEqual(self.mode(directory), 0o700)
            self.assertEqual(self.mode(ledger.path), 0o600)
            self.assertEqual(self.mode(ledger.meta_path), 0o600)
            ledger = Ledger(directory)
            ledger.note_file(_session("b"), os.path.join(root, "b.jsonl"))
            ledger.save()
            self.assertTrue(os.path.isfile(ledger.journal_path))
            self.assertEqual(self.mode(ledger.journal_path), 0o600)

    def test_existing_world_readable_files_are_tightened(self):
        with tempfile.TemporaryDirectory() as root:
            directory = os.path.join(root, "kanjo")
            ledger = Ledger(directory)
            ledger.note_file(_session("a"), os.path.join(root, "a.jsonl"))
            ledger.save()
            ledger = Ledger(directory)
            ledger.note_file(_session("b"), os.path.join(root, "b.jsonl"))
            ledger.save()
            for path in (directory, ledger.path, ledger.meta_path, ledger.journal_path):
                os.chmod(path, 0o755 if path == directory else 0o644)
            ledger = Ledger(directory)
            ledger.note_file(_session("c"), os.path.join(root, "c.jsonl"))
            ledger.save()
            self.assertEqual(self.mode(directory), 0o700)
            self.assertEqual(self.mode(ledger.journal_path), 0o600)
            ledger.forget_orphans()
            self.assertEqual(self.mode(ledger.path), 0o600)
            self.assertEqual(self.mode(ledger.meta_path), 0o600)


if __name__ == "__main__":
    unittest.main()
