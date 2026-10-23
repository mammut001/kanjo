import os
import unittest

from aicost.identity import Resolver, ScratchpadDecoder, normalize_remote, parse_git_config_remotes, pick_remote
from aicost.sources.base import extract_paths

from tests.support import ALICE, GITHUB, FakeFS


class NormalizeRemoteTest(unittest.TestCase):
    def test_spec_examples(self):
        for url in ("git@github.com:cclank/tokei.git", "https://github.com/cclank/tokei",
                    "https://github.com/cclank/tokei.git"):
            self.assertEqual(normalize_remote(url), "github.com/cclank/tokei")

    def test_user_port_case_and_trailing_slash(self):
        self.assertEqual(normalize_remote("ssh://git@GitHub.com:22/CClank/Tokei.git/"), "github.com/cclank/tokei")
        self.assertEqual(normalize_remote("https://user:token@gitlab.com/Group/Sub/Repo.git"),
                         "gitlab.com/group/sub/repo")

    def test_origin_preferred_else_first(self):
        cfg = '[remote "upstream"]\n url = https://github.com/a/x\n[remote "origin"]\n url = git@github.com:b/x.git\n'
        self.assertEqual(pick_remote(parse_git_config_remotes(cfg)), "git@github.com:b/x.git")
        cfg = '[remote "upstream"]\n url = https://github.com/a/x\n[remote "fork"]\n url = https://github.com/c/x\n'
        self.assertEqual(pick_remote(parse_git_config_remotes(cfg)), "https://github.com/a/x")


class ResolverTest(unittest.TestCase):
    def setUp(self):
        self.fs = FakeFS()
        self.main = self.fs.repo(GITHUB + "/FocusApp", [("upstream", "https://github.com/someone/FocusApp"),
                                                        ("origin", "https://github.com/alice/FocusApp.git")])

    def tearDown(self):
        self.fs.cleanup()

    def resolver(self, **kw):
        return Resolver(fs_root=self.fs.root, home=ALICE, **kw)

    def test_plain_repo_uses_origin(self):
        p = self.resolver().resolve(GITHUB + "/FocusApp/Focus/App.swift")
        self.assertEqual(p.id, "github.com/alice/focusapp")
        self.assertEqual(p.name, "FocusApp")  # display name keeps the remote's case
        self.assertEqual(p.remote, "github.com/alice/focusapp")

    def test_worktrees_and_clones_merge(self):
        self.fs.worktree(self.main, GITHUB + "/FocusApp-fixes-146")
        self.fs.worktree(self.main, GITHUB + "/FocusApp-paylag", admin=False)  # pruned admin dir
        self.fs.repo(GITHUB + "/FocusApp-verify-146", [("origin", "git@github.com:alice/FocusApp.git")])  # clone
        r = self.resolver()
        ids = {r.resolve(GITHUB + "/%s/README.md" % d).id
               for d in ("FocusApp", "FocusApp-fixes-146", "FocusApp-paylag", "FocusApp-verify-146")}
        self.assertEqual(ids, {"github.com/alice/focusapp"})
        project = r.project("github.com/alice/focusapp")
        for d in ("FocusApp", "FocusApp-fixes-146", "FocusApp-paylag", "FocusApp-verify-146"):
            self.assertIn(GITHUB + "/" + d, project.paths)
        self.assertFalse(project.path_missing)

    def test_deleted_but_registered_worktree(self):
        wt = "/private/tmp/claude-501/-Users-alice-Documents-GitHub-FocusApp/s1/scratchpad/heat"
        self.fs.worktree(self.main, wt, create_dir=False)
        r = self.resolver()
        r.resolve(GITHUB + "/FocusApp")  # discovering the main repo reads its worktree list
        self.assertEqual(r.resolve(wt + "/Focus/x.swift").id, "github.com/alice/focusapp")
        self.assertEqual(r.resolve(wt.replace("/private/tmp", "/tmp") + "/y").id, "github.com/alice/focusapp")

    def test_repo_without_remote_uses_root_path(self):
        self.fs.repo(GITHUB + "/tcf-canada")
        p = self.resolver().resolve(GITHUB + "/tcf-canada/src/a.ts")
        self.assertEqual(p.id, GITHUB + "/tcf-canada")
        self.assertEqual(p.name, "tcf-canada")
        self.assertIsNone(p.remote)

    def test_not_a_project(self):
        self.fs.mkdir(ALICE + "/Downloads")
        r = self.resolver()
        for path in (ALICE + "/Downloads/a.pdf", "/tmp/x", GITHUB, "/dev/null"):
            self.assertIsNone(r.resolve(path), path)

    def test_missing_file_inside_repo(self):
        self.assertEqual(self.resolver().resolve(GITHUB + "/FocusApp/new/dir/file.swift").id,
                         "github.com/alice/focusapp")

    def test_deleted_project_directory_for_cwd(self):
        self.fs.mkdir(GITHUB)
        r = self.resolver()
        gone = GITHUB + "/old-project"
        self.assertIsNone(r.resolve(gone + "/x.py"))  # file paths never create projects
        p = r.resolve(gone, allow_missing_fallback=True)
        self.assertEqual((p.id, p.name, p.remote, p.path_missing), (gone, "old-project", None, True))
        # temp dirs and agent state dirs are never projects
        self.assertIsNone(r.resolve("/private/tmp/whatever", allow_missing_fallback=True))
        self.assertIsNone(r.resolve(ALICE + "/.codex/worktrees/x", allow_missing_fallback=True))

    def test_remote_hint_only_joins_existing_project(self):
        r = self.resolver()
        r.add_remote_hint("/private/tmp/gone-clone", "https://github.com/alice/FocusApp.git")
        r.add_remote_hint("/private/tmp/other", "https://github.com/alice/unknown.git")
        r.prewarm([GITHUB + "/FocusApp"])
        self.assertEqual(r.resolve("/private/tmp/gone-clone/a.swift").id, "github.com/alice/focusapp")
        self.assertIsNone(r.resolve("/private/tmp/other/a.swift"))

    def test_aliases_merge_fork_and_path(self):
        self.fs.repo(GITHUB + "/tokei-fork", [("origin", "https://github.com/alice/tokei")])
        self.fs.repo(ALICE + "/old-tokei")
        r = self.resolver(aliases={"github.com/cclank/tokei": ["github.com/alice/tokei", ALICE + "/old-tokei"]})
        a = r.resolve(GITHUB + "/tokei-fork/x")
        b = r.resolve(ALICE + "/old-tokei/y")
        self.assertEqual(a.id, "github.com/cclank/tokei")
        self.assertIs(a, b)
        self.assertEqual(a.name, "tokei")
        self.assertEqual(a.remote, "github.com/cclank/tokei")

    def test_fork_is_separate_by_default(self):
        self.fs.repo(GITHUB + "/tokei", [("origin", "https://github.com/cclank/tokei")])
        self.fs.repo(GITHUB + "/tokei-fork", [("origin", "https://github.com/alice/tokei")])
        r = self.resolver()
        self.assertNotEqual(r.resolve(GITHUB + "/tokei/a").id, r.resolve(GITHUB + "/tokei-fork/a").id)

    def test_nested_repo_without_remote_joins_outer(self):
        kit = self.fs.repo(GITHUB + "/FocusApp/Packages/FocusKit")  # no remote
        r = self.resolver()
        p = r.resolve(kit + "/Sources/FocusKit/Timer.swift")
        self.assertEqual(p.id, "github.com/alice/focusapp")
        self.assertIs(p, r.resolve(GITHUB + "/FocusApp/README.md"))
        self.assertIn(kit, p.paths)
        self.assertIn(GITHUB + "/FocusApp", p.paths)
        self.assertEqual(set(r.projects), {"github.com/alice/focusapp"})

    def test_nested_repo_with_remote_stays_separate(self):
        sub = self.fs.repo(GITHUB + "/FocusApp/Vendor/lib", [("origin", "https://github.com/bob/lib.git")])
        self.fs.write(GITHUB + "/FocusApp/Vendor/sub/.git", "gitdir: ../../.git/modules/sub\n")  # submodule
        self.fs.write(GITHUB + "/FocusApp/.git/modules/sub/config",
                      '[remote "origin"]\n\turl = https://github.com/bob/sub\n')
        r = self.resolver()
        self.assertEqual(r.resolve(sub + "/x.c").id, "github.com/bob/lib")
        self.assertEqual(r.resolve(GITHUB + "/FocusApp/Vendor/sub/y.c").id, "github.com/bob/sub")
        self.assertNotIn(sub, r.resolve(GITHUB + "/FocusApp/a.swift").paths)

    def test_two_level_nesting(self):
        mid = self.fs.repo(GITHUB + "/FocusApp/Packages/Mid")
        inner = self.fs.repo(mid + "/Deps/Inner")
        r = self.resolver()
        p = r.resolve(inner + "/a.swift")
        self.assertEqual(p.id, "github.com/alice/focusapp")
        self.assertIs(p, r.resolve(mid + "/b.swift"))
        self.assertTrue({inner, mid} <= p.paths)

    def test_nesting_stops_at_first_repo_with_remote(self):
        mid = self.fs.repo(GITHUB + "/FocusApp/Vendor/mid", [("origin", "https://github.com/bob/mid")])
        inner = self.fs.repo(mid + "/inner")
        r = self.resolver()
        self.assertEqual(r.resolve(inner + "/a").id, "github.com/bob/mid")
        self.assertIn(inner, r.project("github.com/bob/mid").paths)

    def test_nested_in_outer_without_remote_uses_outer_path(self):
        outer = self.fs.repo(GITHUB + "/tcf-canada")
        inner = self.fs.repo(outer + "/packages/core")
        r = self.resolver()
        p = r.resolve(inner + "/index.ts")
        self.assertEqual((p.id, p.name, p.remote), (outer, "tcf-canada", None))
        self.assertIn(inner, p.paths)

    def test_alias_on_nested_path_still_wins(self):
        kit = self.fs.repo(GITHUB + "/FocusApp/Packages/FocusKit")
        r = self.resolver(aliases={"github.com/alice/focuskit": [kit]})
        self.assertEqual(r.resolve(kit + "/a.swift").id, "github.com/alice/focuskit")
        self.assertEqual(r.resolve(GITHUB + "/FocusApp/b.swift").id, "github.com/alice/focusapp")


class ScratchpadTest(unittest.TestCase):
    def test_decodes_dashed_names(self):
        fs = FakeFS()
        try:
            fs.mkdir(GITHUB + "/tcf-canada")
            fs.mkdir(GITHUB + "/tcf")
            fs.mkdir(GITHUB + "/China easy go")
            d = ScratchpadDecoder(fs_root=fs.root)
            self.assertEqual(d.project_path("/private/tmp/claude-501/-Users-alice-Documents-GitHub-tcf-canada/abc/scratchpad/x"),
                             GITHUB + "/tcf-canada")
            self.assertEqual(d.project_path("/tmp/claude-501/-Users-alice-Documents-GitHub-China-easy-go/s/scratchpad"),
                             GITHUB + "/China easy go")
            self.assertIsNone(d.project_path("/private/tmp/claude-501/-Users-alice-Documents-GitHub-deleted/s"))
            self.assertIsNone(d.project_path(GITHUB + "/tcf-canada"))
        finally:
            fs.cleanup()


class ExtractPathsTest(unittest.TestCase):
    def test_truncation_rules(self):
        cmd = "cd /Users/alice/repo; ls /Users/alice/repo2`echo x` && cat '/Users/alice/My Dir/f.txt' \"/opt/x\""
        self.assertEqual(extract_paths(cmd, home="/Users/alice"),
                         ["/Users/alice/My Dir/f.txt", "/opt/x", "/Users/alice/repo", "/Users/alice/repo2"])

    def test_urls_and_relative_paths_ignored(self):
        self.assertEqual(extract_paths("curl https://github.com/a/b && ls src/x ../y", home="/h"), [])

    def test_home_and_trailing_punctuation(self):
        self.assertEqual(extract_paths("ls ~/proj/a.txt, /tmp/b.", home="/Users/alice"),
                         ["/Users/alice/proj/a.txt", "/tmp/b"])


if __name__ == "__main__":
    unittest.main()
