import os
import tempfile
import unittest

from kanjo.ledger import Ledger, marker_key


class LedgerInterruptedJournalTest(unittest.TestCase):
    def test_later_updates_survive_interrupted_journal_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Ledger(directory=tmp)
            ledger.note_unparsed("claude", os.path.join(tmp, "first"))
            ledger.save()
            journal = ledger.journal_path
            with open(journal, "w", encoding="utf-8") as handle:
                handle.write('{"k":"interrupted')
            ledger = Ledger(directory=tmp)
            path = os.path.join(tmp, "second")
            ledger.note_unparsed("claude", path)
            ledger.save()
            self.assertIn(marker_key("claude", path), Ledger(directory=tmp).entries)
