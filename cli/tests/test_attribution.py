import json
import os
import tempfile
import unittest

from aicost import attribution as attr
from aicost.config import Config, ConfigError, from_dict, load, parse_toml_subset
from aicost.export import ScanResult, build_export
from aicost.identity import Resolver, ScratchpadDecoder
from aicost.pricing import PriceBook
from aicost.sources import claude
from aicost.sources.base import Message, Session

from tests.support import ALICE, GITHUB, FakeFS

A = GITHUB + "/proj-a"
B = GITHUB + "/proj-b"
C = GITHUB + "/proj-c"
ID_A, ID_B, ID_C = "github.com/alice/proj-a", "github.com/alice/proj-b", "github.com/alice/proj-c"


def session(sid="s1", cwd=None, calls=(), agent="claude", messages=None, parent=None, branch="main"):
    s = Session(id=sid, agent=agent, file="/x/%s" % sid, cwd=cwd, subagent_of=parent, branch=branch)
    if cwd:
        s.note_cwd(cwd)
    s.tool_paths = [list(c) for c in calls]
    s.messages = messages if messages is not None else [
        Message(ts=1790000000.0, model="claude-opus-5-5", input=1000, output=1000, cwd=cwd, branch=branch,
                key="%s:m1" % sid)]
    for m in s.messages:
        s.note_time(m.ts)
    return s


class DecisionTest(unittest.TestCase):
    def setUp(self):
        self.fs = FakeFS()
        for path, name in ((A, "proj-a"), (B, "proj-b"), (C, "proj-c")):
            self.fs.repo(path, [("origin", "git@github.com:alice/%s.git" % name)])
        self.fs.mkdir(ALICE + "/Downloads")
        self.resolver = Resolver(fs_root=self.fs.root, home=ALICE)
        self.scratch = ScratchpadDecoder(fs_root=self.fs.root)

    def tearDown(self):
        self.fs.cleanup()

    def decide(self, s, threshold=0.8, **cfg):
        return attr.decide(s, self.resolver, self.scratch, Config(dominant_threshold=threshold, **cfg))

    def test_dominant_at_80_percent(self):
        calls = [[A + "/f%d" % i] for i in range(8)] + [[B + "/x"], [B + "/y"]]
        d = self.decide(session(cwd=B, calls=calls))
        self.assertEqual((d.kind, d.shares), ("dominant", [(ID_A, 1.0)]))
        self.assertEqual(d.scores, {ID_A: 8, ID_B: 2})

    def test_split_below_threshold(self):
        calls = [[A + "/f%d" % i] for i in range(6)] + [[B + "/x%d" % i] for i in range(4)]
        d = self.decide(session(calls=calls))
        self.assertEqual(d.kind, "split")
        self.assertEqual(d.shares, [(ID_A, 0.6), (ID_B, 0.4)])

    def test_threshold_one_always_splits_mixed(self):
        calls = [[A + "/f%d" % i] for i in range(9)] + [[B + "/x"]]
        self.assertEqual(self.decide(session(calls=calls), threshold=1.0).kind, "split")
        self.assertEqual(self.decide(session(calls=[[A + "/f"]]), threshold=1.0).kind, "dominant")

    def test_threshold_half_tie_goes_to_cwd(self):
        calls = [[A + "/f"], [B + "/x"]]
        d = self.decide(session(cwd=B, calls=calls), threshold=0.5)
        self.assertEqual(d.shares, [(ID_B, 1.0)])

    def test_same_path_in_one_call_scores_once(self):
        calls = [[A + "/f", A + "/f", A + "/g"], [B + "/x"]]
        self.assertEqual(self.decide(session(calls=calls)).scores, {ID_A: 2, ID_B: 1})

    def test_unmapped_paths_score_nothing(self):
        d = self.decide(session(cwd=C, calls=[["/tmp/x"], [ALICE + "/Downloads/y.pdf"], ["/dev/null"]]))
        self.assertEqual((d.kind, d.shares), ("cwd", [(ID_C, 1.0)]))

    def test_scratchpad_fallback(self):
        cwd = "/private/tmp/claude-501/-Users-alice-Documents-GitHub-proj-b/abc/scratchpad/wt"
        d = self.decide(session(cwd=cwd, calls=[[cwd + "/deleted/file.ts"]]))
        self.assertEqual((d.kind, d.shares), ("scratchpad", [(ID_B, 1.0)]))

    def test_unattributed(self):
        d = self.decide(session(cwd=ALICE + "/Downloads"))
        self.assertEqual((d.kind, d.shares), ("none", [(attr.UNATTRIBUTED, 1.0)]))

    def test_override_and_exclude_longest_prefix(self):
        cfg = dict(overrides={GITHUB + "/proj-": "github.com/cclank/tokei"}, exclude=[GITHUB + "/proj-c"])
        d = self.decide(session(cwd=A, calls=[[B + "/x"]]), **cfg)
        self.assertEqual((d.kind, d.shares), ("override", [("github.com/cclank/tokei", 1.0)]))
        d = self.decide(session(cwd=C + "/sub", calls=[[A + "/x"]]), **cfg)
        self.assertEqual(d.kind, "excluded")


class ExportAttributionTest(unittest.TestCase):
    """Sub-agents, splitting and de-duplication through the whole pipeline."""

    def setUp(self):
        self.fs = FakeFS()
        self.fs.repo(A, [("origin", "git@github.com:alice/proj-a.git")])
        self.fs.repo(B, [("origin", "git@github.com:alice/proj-b.git")])

    def tearDown(self):
        self.fs.cleanup()

    def export(self, sessions, **kw):
        return build_export(scan_result=ScanResult(sessions=sessions, failed_files=[], stats={}),
                            fs_root=self.fs.root, home=ALICE, **kw)

    def test_subagent_follows_parent_split(self):
        parent = session("p", calls=[[A + "/1"], [A + "/2"], [A + "/3"], [B + "/1"], [B + "/2"]])
        sub = session("p/agent-1", parent="p", calls=[[B + "/only-b"]] * 5,
                      messages=[Message(ts=1790000100.0, model="claude-opus-5-5", input=0, output=10000, key="sub:1")])
        doc = self.export([parent, sub])
        by_id = {p["id"]: p for p in doc["projects"]}
        a, b = by_id[ID_A], by_id[ID_B]
        sa, sb = a["sessions_detail"][0], b["sessions_detail"][0]
        self.assertEqual((sa["share"], sb["share"]), (0.6, 0.4))
        self.assertEqual((sa["subagents"], sa["attribution"]), (1, "split"))
        total = doc["totals"]["cost"]
        self.assertAlmostEqual(a["cost"], total * 0.6, places=3)
        self.assertEqual(doc["totals"]["unique_sessions"], 1)
        self.assertEqual(doc["totals"]["sessions"], 2)  # a split session counts once per project
        self.assertEqual(sa["tokens"]["output"] + sb["tokens"]["output"], 11000)

    def test_orphan_subagent_scored_independently(self):
        orphan = session("gone/agent-1", parent="gone", calls=[[B + "/x"]])
        doc = self.export([orphan])
        self.assertEqual([p["id"] for p in doc["projects"]], [ID_B])

    def test_duplicate_message_keys_billed_once(self):
        m = lambda: Message(ts=1790000000.0, model="claude-opus-5-5", input=100, output=100, key="claude:msg_1")
        original = session("orig", cwd=A, messages=[m()])
        original.origin_ts = 1789990000.0
        fork = session("fork", cwd=A, messages=[m(), Message(ts=1790000500.0, model="claude-opus-5-5",
                                                            input=1, output=1, key="claude:msg_2")])
        fork.origin_ts = 1790000400.0
        doc = self.export([fork, original])
        detail = {s["id"]: s for s in doc["projects"][0]["sessions_detail"]}
        self.assertEqual(detail["orig"]["tokens"]["output"], 100)
        self.assertEqual(detail["fork"]["tokens"]["output"], 1)  # copied history not billed again

    def test_by_branch_empty_without_branches(self):
        doc = self.export([session("s", cwd=A, branch=None, messages=[
            Message(ts=1790000000.0, model="claude-opus-5-5", input=1, output=1, branch=None, key="k")])])
        self.assertEqual(doc["projects"][0]["by_branch"], [])
        doc = self.export([session("s", cwd=A, messages=[
            Message(ts=1790000000.0, model="claude-opus-5-5", input=1, output=1, branch=None, key="k1"),
            Message(ts=1790000001.0, model="claude-opus-5-5", input=1, output=1, branch="main", key="k2")])])
        self.assertEqual({b["branch"] for b in doc["projects"][0]["by_branch"]}, {"main", "(unknown)"})

    def test_excluded_bucket(self):
        doc = self.export([session("s", cwd=A, calls=[[A + "/x"]])], config=Config(exclude=[A]))
        self.assertEqual(doc["projects"], [])
        ex = doc["buckets"]["excluded"]
        self.assertEqual((ex["sessions"], ex["sessions_detail"][0]["attribution"]), (1, "excluded"))
        self.assertAlmostEqual(ex["cost"], doc["totals"]["cost"], places=4)


class ClaudeStreamingTest(unittest.TestCase):
    def test_last_line_of_message_id_wins_and_tools_from_all_lines(self):
        lines = []
        base = {"type": "assistant", "cwd": GITHUB + "/proj-a", "sessionId": "abc", "gitBranch": "main"}
        for i, (block, out) in enumerate(((
                {"type": "thinking", "thinking": ""}, 5),
                ({"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": A + "/one.py"}}, 50),
                ({"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "ls %s/two" % B}}, 99))):
            lines.append(dict(base, timestamp="2026-10-01T00:00:0%dZ" % i, uuid="u%d" % i, message={
                "id": "msg_1", "model": "claude-opus-5-5", "content": [block],
                "usage": {"input_tokens": 3, "output_tokens": out, "cache_read_input_tokens": 10,
                          "cache_creation_input_tokens": 20,
                          "cache_creation": {"ephemeral_1h_input_tokens": 20, "ephemeral_5m_input_tokens": 0}}}))
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w") as h:
            for line in lines:
                h.write(json.dumps(line) + "\n")
        try:
            s = claude.parse_file(path)
        finally:
            os.remove(path)
        self.assertEqual(len(s.messages), 1)
        self.assertEqual((s.messages[0].output, s.messages[0].cache_write_1h), (99, 20))
        self.assertEqual(s.tool_paths, [[A + "/one.py"], [B + "/two"]])
        self.assertEqual((s.id, s.branch, s.cwd), ("abc", "main", A))


class ConfigTest(unittest.TestCase):
    SPEC_EXAMPLE = '''
# 项目别名：把多个标识合并成一个
[aliases]
"github.com/cclank/tokei" = ["github.com/dogecoin/tokei", "/Users/dogecoin/old-tokei"]

# 强制归属
[overrides]
"/Users/dogecoin/Documents/experiments/tokei-" = "github.com/cclank/tokei"

# 排除
exclude = ["/Users/dogecoin/scratch"]

# 主项目阈值
dominant_threshold = 0.8
'''

    def test_spec_example(self):
        cfg = from_dict(parse_toml_subset(self.SPEC_EXAMPLE))
        self.assertEqual(cfg.aliases, {"github.com/cclank/tokei": ["github.com/dogecoin/tokei", "/Users/dogecoin/old-tokei"]})
        self.assertEqual(cfg.overrides, {"/Users/dogecoin/Documents/experiments/tokei-": "github.com/cclank/tokei"})
        self.assertEqual(cfg.exclude, ["/Users/dogecoin/scratch"])
        self.assertEqual(cfg.dominant_threshold, 0.8)
        self.assertEqual(cfg.match_override("/Users/dogecoin/Documents/experiments/tokei-v2/x"),
                         ("override", "github.com/cclank/tokei"))
        self.assertEqual(cfg.match_override("/Users/dogecoin/scratch/y"), ("exclude", None))
        self.assertIsNone(cfg.match_override("/Users/dogecoin/other"))

    def test_json_file_and_validation(self):
        d = tempfile.mkdtemp()
        try:
            path = os.path.join(d, "attribution.json")
            with open(path, "w") as h:
                json.dump({"dominant_threshold": 0.5, "exclude": ["/x"]}, h)
            cfg = load(path)
            self.assertEqual((cfg.dominant_threshold, cfg.exclude, cfg.source), (0.5, ["/x"], path))
            with self.assertRaises(ConfigError):
                from_dict({"dominant_threshold": 1.5})
            with self.assertRaises(ConfigError):
                load(os.path.join(d, "missing.toml"))
        finally:
            import shutil
            shutil.rmtree(d)


class PricingTest(unittest.TestCase):
    def setUp(self):
        self.book = PriceBook()

    def test_exact_and_estimated(self):
        self.assertEqual(self.book.resolve("claude-opus-5-5"), ("anthropic/claude-opus-5.5", False))
        self.assertEqual(self.book.resolve("claude-opus-5-5-20260921"), ("anthropic/claude-opus-5.5", False))
        self.assertEqual(self.book.resolve("gpt-5.6-sol"), ("openai/gpt-5.6-sol", False))
        self.assertEqual(self.book.resolve("gemini-3.8-flash-n"), ("google/gemini-3.8-flash", True))
        self.assertEqual(self.book.resolve("claude-opus-5-5-high"), ("anthropic/claude-opus-5.5", True))
        self.assertEqual(self.book.resolve("gemini-pro-default"), ("google/gemini-3.1-pro-preview", True))
        self.assertEqual(self.book.resolve("totally-new-model", "codex"), ("openai/gpt-6-astra", True))
        self.assertEqual(self.book.resolve("<synthetic>"), (None, False))

    def test_cost_formula(self):
        # opus 5.5: in 4, out 20, cache read 0.2, 5m write 5, 1h write 8 (2x input) per 1M
        cost, est = self.book.cost("claude-opus-5-5", "claude", 1_000_000, 1_000_000, 1_000_000, 2_000_000, 1_000_000)
        self.assertFalse(est)
        self.assertAlmostEqual(cost, 4 + 20 + 0.2 + 5 + 8)


if __name__ == "__main__":
    unittest.main()
