"""Privacy checks against the same synthetic sessions used by the CLI tests."""
import hashlib
import json
import os
import unittest
from unittest import mock

from kanjo import export
from kanjo.config import Config
from tests.support import ALICE, FIXTURE_DIRS, FIXTURES, standard_fs


class OutboundFixturePrivacyTest(unittest.TestCase):
    def test_fixture_payloads(self):
        fs = standard_fs()
        self.addCleanup(fs.cleanup)
        with mock.patch('kanjo.export.build_device_info', return_value={'id': '0123456789abcdef', 'name': 'device', 'os': 'macos'}), \
             mock.patch('kanjo.export.quota.quota_windows', return_value={}), \
             mock.patch('kanjo.export.load_subscriptions', return_value={}):
            full = export.build_export(dirs=FIXTURE_DIRS, fs_root=fs.root, home=ALICE,
                                       tokei_dir=os.path.join(FIXTURES, 'no-tokei'))
            mobile = export.mobile_document(full)
            hidden = export.mobile_document(full, hide_project_names=True)
            public = export.build_public_summary(dirs=FIXTURE_DIRS, fs_root=fs.root, home=ALICE)
            family = export.build_family_report(config=Config(), dirs=FIXTURE_DIRS,
                                                fs_root=fs.root, home=ALICE)
        sensitive = {ALICE, '/Users/', '/home/', 'alice', 'github.com/alice'}
        names = set()
        for project in full['projects']:
            names.update((project['name'], project['id']))
            sensitive.update(project.get('paths', []))
            if project.get('remote'):
                sensitive.add(project['remote'])
            for session in project.get('sessions_detail', []):
                sensitive.update(session.get(k) for k in ('title', 'cwd', 'branch') if session.get(k))
        for payload in (mobile, hidden, public, family):
            text = json.dumps(payload).lower()
            for value in sensitive:
                if value and len(value) >= 4:
                    self.assertNotIn(value.lower(), text)
        for payload in (hidden, public, family):
            text = json.dumps(payload).lower()
            for value in names:
                if value and len(value) >= 4:
                    self.assertNotIn(value.lower(), text)
                    self.assertNotIn(hashlib.sha256(value.encode()).hexdigest()[:12], text)
