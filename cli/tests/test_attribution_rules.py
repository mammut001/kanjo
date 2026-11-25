"""Executable examples for ATTRIBUTION.md; rule numbers refer to that document."""
import os
import unittest
from datetime import datetime

from kanjo import attribution as attr
from kanjo.config import Config
from kanjo.export import ScanResult, build_export
from kanjo.identity import Resolver, ScratchpadDecoder, normalize_remote
from kanjo.sources.base import Message
from tests.support import ALICE, GITHUB, standard_fs
from tests.test_attribution import session

A = GITHUB + '/FocusApp'
B = GITHUB + '/other'
IA = 'github.com/alice/focusapp'
IB = 'github.com/alice/other'


class AttributionRules(unittest.TestCase):
    def setUp(self):
        self.fs = standard_fs()
        self.fs.repo(B, [('origin', 'git@github.com:alice/other.git')])
        self.resolver = Resolver(fs_root=self.fs.root, home=ALICE)
        self.scratch = ScratchpadDecoder(fs_root=self.fs.root)

    def tearDown(self):
        self.fs.cleanup()

    def decision(self, cwd=None, calls=(), **config):
        return attr.decide(session(cwd=cwd, calls=calls), self.resolver,
                           self.scratch, Config(**config))

    def export(self, sessions, **kwargs):
        return build_export(scan_result=ScanResult(sessions=sessions, failed_files=['bad.log'], stats={}),
                            fs_root=self.fs.root, home=ALICE, **kwargs)

    def test_2_identity_and_remote_normalization(self):
        for url in ('git@github.com:Alice/FocusApp.git',
                    'https://github.com/Alice/FocusApp',
                    'https://user@github.com/Alice/FocusApp.git/'):
            with self.subTest(url=url):
                self.assertEqual(normalize_remote(url), IA)
        self.fs.repo(GITHUB + '/clone', [('upstream', 'https://github.com/alice/FocusApp')])
        self.fs.repo(GITHUB + '/fork', [('origin', 'https://github.com/bob/FocusApp')])
        self.fs.repo(GITHUB + '/local')
        self.fs.repo(A + '/nested')
        self.fs.repo(A + '/nested/inner')
        self.fs.repo(A + '/independent', [('origin', 'https://github.com/bob/independent')])
        wt = GITHUB + '/worktree'
        self.fs.worktree(A, wt)
        cases = [(A, IA), (GITHUB + '/clone', IA), (GITHUB + '/fork', 'github.com/bob/focusapp'),
                 (GITHUB + '/local', GITHUB + '/local'), (A + '/nested/inner', IA),
                 (A + '/independent', 'github.com/bob/independent'), (wt, IA)]
        for path, expected in cases:
            with self.subTest(path=path):
                self.assertEqual(self.resolver.resolve(path, True).id, expected)
        self.assertIsNone(self.resolver.resolve(ALICE + '/Downloads'))

    def test_3_4_scoring_and_precedence(self):
        scratch = '/private/tmp/claude-501/-Users-alice-Documents-GitHub-FocusApp/s/scratchpad'
        cases = [
            ('files beat cwd', B, [[A + '/x']], {}, 'dominant', [(IA, 1.0)]),
            ('cwd beats scratch', B, [[scratch + '/x']], {}, 'cwd', [(IB, 1.0)]),
            ('scratch fallback', scratch, [], {}, 'scratchpad', [(IA, 1.0)]),
            ('no signals', ALICE, [], {}, 'none', [(attr.UNATTRIBUTED, 1.0)]),
            ('80 percent', B, [[A + '/x']]*8 + [[B + '/y']]*2, {}, 'dominant', [(IA, 1.0)]),
            ('proportional', B, [[A + '/x']]*6 + [[B + '/y']]*4, {}, 'split', [(IA, .6), (IB, .4)]),
            ('threshold one', B, [[A + '/x']]*9 + [[B + '/y']], {'dominant_threshold': 1.0}, 'split', [(IA, .9), (IB, .1)]),
            ('threshold half', B, [[A + '/x']]*3 + [[B + '/y']]*2, {'dominant_threshold': .5}, 'dominant', [(IA, 1.0)]),
            ('tie uses cwd', B, [[A + '/x'], [B + '/y']], {'dominant_threshold': .5}, 'dominant', [(IB, 1.0)]),
        ]
        for name, cwd, calls, cfg, kind, shares in cases:
            with self.subTest(rule=name):
                d = self.decision(cwd, calls, **cfg)
                self.assertEqual((d.kind, d.shares), (kind, shares))
        self.assertEqual(self.decision(calls=[[A + '/x', A + '/x'], [B + '/x']]).scores, {IA: 1, IB: 1})
        changed_cwd = session(cwd=A)
        changed_cwd.note_cwd(B, 2)
        self.assertEqual(attr.decide(changed_cwd, self.resolver, self.scratch, Config()).shares, [(IB, 1.0)])

    def test_5_subagents_follow_parent_and_orphans_score(self):
        parent = session('parent', calls=[[A + '/x']]*3 + [[B + '/x']]*2)
        child = session('child', parent='parent', calls=[[B + '/x']]*10)
        orphan = session('orphan', parent='missing', calls=[[B + '/x']])
        doc = self.export([parent, child, orphan])
        projects = {p['id']: p for p in doc['projects']}
        for pid, share in ((IA, .6), (IB, .4)):
            detail = next(d for d in projects[pid]['sessions_detail'] if d['id'] == 'parent')
            self.assertEqual((detail['share'], detail['subagents']), (share, 1))
        self.assertTrue(any(d['id'] == 'orphan' for d in projects[IB]['sessions_detail']))
        dominant = session('dominant', calls=[[A + '/x']])
        child = session('child2', parent='dominant', calls=[[B + '/x']])
        projects = self.export([dominant, child])['projects']
        self.assertEqual([p['id'] for p in projects], [IA])
        self.assertEqual(projects[0]['sessions_detail'][0]['subagents'], 1)

    def test_6_message_days_and_branches(self):
        messages = [Message(ts=datetime(2026, 10, 1, 12).timestamp(), model='claude-opus-5-5', output=10000, branch='one', key='one'),
                    Message(ts=datetime(2026, 10, 2, 12).timestamp(), model='claude-opus-5-5', output=20000, branch='two', key='two')]
        doc = self.export([session(cwd=A, messages=messages)])
        project = doc['projects'][0]
        self.assertEqual([d['day'] for d in project['by_day']], ['2026-10-01', '2026-10-02'])
        self.assertAlmostEqual(project['by_day'][1]['cost'], 2 * project['by_day'][0]['cost'])
        self.assertEqual({x['branch'] for x in project['by_branch']}, {'one', 'two'})

    def test_8_overrides_excludes_aliases(self):
        cases = [([A], {A: IB}, 'excluded', attr.EXCLUDED),
                 ([A], {A + '/sub': IB}, 'override', IB),
                 ([A + '/sub'], {A: IB}, 'excluded', attr.EXCLUDED)]
        for excludes, overrides, kind, pid in cases:
            with self.subTest(excludes=excludes, overrides=overrides):
                d = self.decision(A + '/sub', [[A + '/x']], exclude=excludes, overrides=overrides)
                self.assertEqual((d.kind, d.shares), (kind, [(pid, 1.0)]))
        resolver = Resolver(fs_root=self.fs.root, home=ALICE, aliases={IA: [IB]})
        self.assertEqual(resolver.resolve(B).id, IA)

    def test_9_missing_and_symlink(self):
        missing = GITHUB + '/deleted'
        p = self.resolver.resolve(missing, True)
        self.assertEqual((p.id, p.name, p.path_missing), (missing, 'deleted', True))
        os.symlink(self.fs.real(A), self.fs.real(GITHUB + '/link'))
        self.assertEqual(self.resolver.resolve(GITHUB + '/link/file').id, IA)
        for suffix in (';', '\n'):
            self.assertEqual(self.resolver.resolve(A + suffix).id, IA)

    def test_10_buckets_and_reconciliation(self):
        doc = self.export([session('a', cwd=A), session('u', cwd=ALICE + '/.claude'),
                           session('x', cwd=B)], config=Config(exclude=[B]))
        self.assertIn('API-equivalent', doc['cost_note'])
        self.assertIn('subscription', doc['cost_note'])
        self.assertEqual(doc['buckets']['parse_failed']['sessions'], 1)
        self.assertEqual(doc['buckets']['unattributed']['sessions'], 1)
        self.assertEqual(doc['buckets']['excluded']['sessions'], 1)
        total = sum(p['cost'] for p in doc['projects'])
        total += doc['buckets']['unattributed']['cost'] + doc['buckets']['excluded']['cost']
        self.assertAlmostEqual(total, doc['totals']['cost'], places=3)

    def test_4_3_non_git_folder_is_its_own_project(self):
        folder = ALICE + '/Documents/校招'
        self.fs.mkdir(folder + '/notes')
        d = self.decision(folder)
        self.assertEqual((d.kind, d.shares), ('cwd', [(folder, 1.0)]))
        project = self.resolver.project(folder)
        self.assertEqual((project.name, project.remote, project.path_missing), ('校招', None, False))
        # a sub-folder is its own folder project, named after itself
        d = self.decision(folder + '/notes')
        self.assertEqual(d.shares, [(folder + '/notes', 1.0)])
        # same id as the deleted-folder fallback, so deleting the folder keeps the project
        gone = ALICE + '/Documents/old-notes'
        self.assertEqual(self.decision(gone).shares, [(gone, 1.0)])
        # git signals still win; file operations inside the folder score nothing
        d = self.decision(folder, [[A + '/x'], [folder + '/a.md']])
        self.assertEqual((d.kind, d.shares), ('dominant', [(IA, 1.0)]))
        # the most used cwd wins
        s = session(cwd=folder)
        other = self.fs.mkdir(ALICE + '/Desktop/draft')
        s.note_cwd(folder, 1)
        s.note_cwd(other, 3)
        self.assertEqual(attr.decide(s, self.resolver, self.scratch, Config()).shares, [(other, 1.0)])
        # excludes and overrides still come first
        self.assertEqual(self.decision(folder, exclude=[folder]).kind, 'excluded')

    def test_4_3_folder_project_exceptions(self):
        for path in (ALICE + '/.gemini/antigravity/brain/x/scratch', ALICE + '/.claude/projects',
                     ALICE + '/.codex', ALICE + '/.cursor/x', ALICE + '/.grok', ALICE + '/.qwen',
                     ALICE + '/.local/share/kanjo', ALICE + '/Library/Application Support/Qoder',
                     ALICE + '/AppData/Roaming/x', '/tmp/work', '/private/tmp/work',
                     '/var/folders/ab/T/work', '/opt/elsewhere'):
            self.fs.mkdir(path)
        cases = [ALICE, None, ALICE + '/.gemini/antigravity/brain/x/scratch', ALICE + '/.claude/projects',
                 ALICE + '/.codex', ALICE + '/.cursor/x', ALICE + '/.grok', ALICE + '/.qwen',
                 ALICE + '/.local/share/kanjo', ALICE + '/Library/Application Support/Qoder',
                 ALICE + '/AppData/Roaming/x', '/tmp/work', '/private/tmp/work',
                 '/var/folders/ab/T/work', '/opt/elsewhere', '/Users', '/']
        for cwd in cases:
            with self.subTest(cwd=cwd):
                d = self.decision(cwd)
                self.assertEqual((d.kind, d.shares), ('none', [(attr.UNATTRIBUTED, 1.0)]))
                if cwd:
                    self.assertIsNone(self.resolver.folder_project(cwd))
        # the system temporary directory, wherever it is
        import tempfile
        tmp_home = os.path.realpath(tempfile.gettempdir())
        r = Resolver(home=os.path.dirname(tmp_home))
        self.assertIsNone(r.folder_project(tmp_home))

    def test_4_3_codex_app_chat_folders_are_tool_folders(self):
        codex = ALICE + '/Documents/Codex'
        chats = [codex, codex + '/2026-11-19', codex + '/2026-11-19/ni', codex + '/2026-11-19/new-chat',
                 codex + '/2026-11-19/hi', codex + '/2026-08-06-musespark1-2', ALICE + '/documents/codex/x']
        for path in chats:
            self.fs.mkdir(path)
        for cwd in chats:
            with self.subTest(cwd=cwd):
                self.assertEqual(self.decision(cwd).kind, 'none')
        # real working folders still become projects, also with similar names
        for cwd in (GITHUB + '/5170-project', ALICE + '/Documents/校招', ALICE + '/Documents/dti5170 project',
                    ALICE + '/work-int/gk', ALICE + '/Documents/Codex-notes', ALICE + '/Codex/x'):
            self.fs.mkdir(cwd)
            with self.subTest(cwd=cwd):
                self.assertEqual(self.decision(cwd).shares, [(cwd, 1.0)])

    def test_4_3_folder_project_in_export(self):
        folder = self.fs.mkdir(ALICE + '/Documents/校招')
        doc = self.export([session('f', cwd=folder), session('h', cwd=ALICE)])
        by_id = {p['id']: p for p in doc['projects']}
        self.assertIn(folder, by_id)
        p = by_id[folder]
        self.assertEqual((p['name'], p['remote'], p['paths'], p['path_missing']), ('校招', None, [folder], False))
        self.assertEqual(p['sessions_detail'][0]['attribution'], 'cwd')
        self.assertEqual(doc['buckets']['unattributed']['sessions'], 1)

    def test_case_insensitive_filesystem(self):
        if not os.path.exists(self.fs.real(A.lower())):
            self.skipTest('filesystem is case-sensitive')
        self.assertEqual(self.resolver.resolve(A.lower() + '/file').id, IA)
