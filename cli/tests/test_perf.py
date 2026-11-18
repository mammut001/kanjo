"""Tests for output speed (tok/s) and TTFT timing (CONTRACT.md section 5.1)."""

import json
import math
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest import mock

from kanjo import perf
from kanjo.cache import CACHE_VERSION, SessionCache, _dump_session, _load_session
from kanjo.config import Config
from kanjo.export import (
    ScanResult,
    build_export,
    build_family_report,
    build_public_summary,
    mobile_document,
)
from kanjo.sources import antigravity, claude, codex, grok
from kanjo.sources.base import Message, Session

from tests.support import ALICE, FIXTURES, GITHUB, FakeFS, standard_fs, validate_contract

PERF_FIXTURES = os.path.join(FIXTURES, "perf")
NO_TOKEI = os.path.join(FIXTURES, "no-tokei")


def _pb_varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _pb_bytes(fn: int, payload: bytes) -> bytes:
    return _pb_varint((fn << 3) | 2) + _pb_varint(len(payload)) + payload


def _pb_varint_field(fn: int, val: int) -> bytes:
    return _pb_varint((fn << 3) | 0) + _pb_varint(val)


def _pb_duration(seconds: int, nanos: int = 0) -> bytes:
    data = _pb_varint_field(1, seconds)
    if nanos:
        data += _pb_varint_field(2, nanos)
    return data


class PerfMathTest(unittest.TestCase):
    def test_ttft_bucket_and_boundaries(self):
        # Bucket 0 = [0, 0.05)
        self.assertEqual(perf.ttft_bucket(0.0), 0)
        self.assertEqual(perf.ttft_bucket(0.0499), 0)
        # Bucket 1 = [0.05, 0.05 * 1.05)
        self.assertEqual(perf.ttft_bucket(0.05), 1)
        self.assertEqual(perf.ttft_bucket(0.0524), 1)
        # Bucket 2 = [0.05 * 1.05, 0.05 * 1.05^2)
        self.assertEqual(perf.ttft_bucket(0.05 * 1.05), 2)
        # Bucket 47 lower/upper bounds check
        low, high = perf.ttft_bounds(47)
        self.assertAlmostEqual(low, 0.05 * (1.05 ** 46), places=12)
        self.assertAlmostEqual(high, 0.05 * (1.05 ** 47), places=12)
        mid = (low + high) / 2.0
        self.assertEqual(perf.ttft_bucket(mid), 47)

    def test_ttft_median_hand_computed(self):
        self.assertIsNone(perf.ttft_median({}))
        self.assertIsNone(perf.ttft_median({"0": 0}))

        # Single sample in bucket 62: midpoint of [0.05*1.05^61, 0.05*1.05^62)
        low62, high62 = perf.ttft_bounds(62)
        expected_single = round((low62 + high62) / 2.0, 2)
        self.assertEqual(perf.ttft_median({"62": 1}), expected_single)

        # Odd count across multiple buckets:
        # bucket 50 (count=2), bucket 70 (count=3), bucket 90 (count=2) -> total=7, median rank=4 (2nd in bucket 70)
        low70, high70 = perf.ttft_bounds(70)
        expected_odd = round(low70 + (high70 - low70) * ((4 - 2 - 0.5) / 3), 2)
        self.assertEqual(perf.ttft_median({"50": 2, "70": 3, "90": 2}), expected_odd)

        # Even count where the two middle ranks fall in DIFFERENT buckets:
        # bucket 60 (count=2) and bucket 80 (count=2) -> total=4, ranks 2 and 3
        low60, high60 = perf.ttft_bounds(60)
        low80, high80 = perf.ttft_bounds(80)
        r2 = low60 + (high60 - low60) * ((2 - 0 - 0.5) / 2)
        r3 = low80 + (high80 - low80) * ((3 - 2 - 0.5) / 2)
        expected_even_split = round((r2 + r3) / 2.0, 2)
        self.assertEqual(perf.ttft_median({"60": 2, "80": 2}), expected_even_split)

        # Even count within the SAME bucket (count=4 in bucket 75): ranks 2 and 3
        low75, high75 = perf.ttft_bounds(75)
        s2 = low75 + (high75 - low75) * (1.5 / 4)
        s3 = low75 + (high75 - low75) * (2.5 / 4)
        self.assertEqual(perf.ttft_median({"75": 4}), round((s2 + s3) / 2.0, 2))

    def test_sample_filter_limits_and_ttft_bounds(self):
        acc = {}
        # Output < 20 dropped; 20 kept
        self.assertFalse(perf.add_sample(acc, "k", 19, 1.0, 0.5))
        self.assertTrue(perf.add_sample(acc, "k", 20, 1.0, 0.5))

        # gen <= 0.2 dropped; gen > 1800 dropped; boundary 1800.0 kept
        self.assertFalse(perf.add_sample(acc, "k", 50, 0.2, 0.1))
        self.assertTrue(perf.add_sample(acc, "k", 50, 0.201, 0.1))
        self.assertFalse(perf.add_sample(acc, "k", 50, 1800.001, 0.1))
        self.assertTrue(perf.add_sample(acc, "k", 50, 1800.0, 0.1))

        # output / gen > 3000 dropped; exact 3000.0 kept
        self.assertFalse(perf.add_sample(acc, "k", 3001, 1.0, 0.1))
        self.assertTrue(perf.add_sample(acc, "k", 3000, 1.0, 0.1))

        # Non-finite gen rejected
        self.assertFalse(perf.add_sample(acc, "k", 100, float("nan"), 0.1))
        self.assertFalse(perf.add_sample(acc, "k", 100, float("inf"), 0.1))

        # TTFT outside [0, 120] drops only the TTFT bucket, still counts o/g/n
        ttft_acc = {}
        self.assertTrue(perf.add_sample(ttft_acc, "k", 100, 2.0, -0.001))
        self.assertTrue(perf.add_sample(ttft_acc, "k", 100, 2.0, 120.001))
        self.assertEqual(ttft_acc["k"]["n"], 2)
        self.assertEqual(ttft_acc["k"]["th"], {})

        self.assertTrue(perf.add_sample(ttft_acc, "k", 100, 2.0, 0.0))
        self.assertTrue(perf.add_sample(ttft_acc, "k", 100, 2.0, 120.0))
        self.assertEqual(ttft_acc["k"]["th"]["0"], 1)
        self.assertEqual(ttft_acc["k"]["th"][str(perf.ttft_bucket(120.0))], 1)


class SourceTimingTest(unittest.TestCase):
    def test_claude_fixture_with_and_without_thinking_duration(self):
        path = os.path.join(
            PERF_FIXTURES, "claude", "-Users-alice-Documents-GitHub-FocusApp", "perf-claude-1.jsonl"
        )
        session = claude.parse_file(path)
        self.assertEqual(len(session.messages), 2)

        # Request 1: user at 10:00:00.000, attachment skipped, first block at 10:00:02.000
        # with thinkingDurationMs=1500 -> first=10:00:00.500, end=10:00:04.500
        # gen = 4.0s, ttft = 0.5s
        m1 = session.messages[0]
        self.assertEqual(m1.output, 150)
        self.assertEqual(m1.gen_s, 4.0)
        self.assertEqual(m1.ttft_s, 0.5)

        # Request 2: user at 10:01:00.000, no thinkingDurationMs, last block at 10:01:05.000
        # gen = 5.0s, ttft = None
        m2 = session.messages[1]
        self.assertEqual(m2.output, 100)
        self.assertEqual(m2.gen_s, 5.0)
        self.assertIsNone(m2.ttft_s)

    def test_claude_large_user_tool_result_fast_path(self):
        tmp = tempfile.mkdtemp(prefix="kanjo-claude-perf-")
        self.addCleanup(shutil.rmtree, tmp, True)
        path = os.path.join(tmp, "sess.jsonl")
        big_pad = "x" * 10000
        lines = [
            json.dumps({"parentUuid": None, "type": "user", "uuid": "u0",
                        "timestamp": "2026-11-17T10:00:00.000Z", "message": {"role": "user", "content": "hi"}}),
            json.dumps({"parentUuid": "u0", "type": "assistant", "uuid": "a0",
                        "timestamp": "2026-11-17T10:00:01.000Z", "requestId": "r0",
                        "message": {"id": "m0", "model": "claude-opus-5-5",
                                    "usage": {"input_tokens": 10, "output_tokens": 25}}}),
            # Large tool_result user line (>8KB) after session.title is already set:
            '{"parentUuid":"a0","isSidechain":false,"type":"user","uuid":"u1","timestamp":"2026-11-17T10:00:02.000Z","message":{"role":"user","content":"' + big_pad + '"}}',
            json.dumps({"parentUuid": "u1", "type": "assistant", "uuid": "a1",
                        "timestamp": "2026-11-17T10:00:05.500Z", "requestId": "r1",
                        "message": {"id": "m1", "model": "claude-opus-5-5",
                                    "usage": {"input_tokens": 20, "output_tokens": 80}}}),
        ]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        session = claude.parse_file(path)
        self.assertEqual(len(session.messages), 2)
        self.assertEqual(session.messages[0].gen_s, 1.0)
        self.assertEqual(session.messages[1].gen_s, 3.5)
        self.assertIsNone(session.messages[1].ttft_s)

    def test_codex_fixtures_produce_samples(self):
        # New fixture with item_completed (started_at_ms) + trigger-only second request
        path = os.path.join(
            PERF_FIXTURES, "codex", "2026", "11", "17",
            "rollout-2026-11-17T10-00-00-perf-codex-1.jsonl",
        )
        session = codex.parse_file(path)
        self.assertEqual(len(session.messages), 2)
        # First: user at 10:00:01.000, Reasoning started_at_ms=10:00:01.800, token_count at 10:00:05.800
        self.assertEqual(session.messages[0].gen_s, 4.0)
        self.assertEqual(session.messages[0].ttft_s, 0.8)
        # Second: function_call_output at 10:00:06.000, token_count at 10:00:09.000 (no item_completed)
        self.assertEqual(session.messages[1].gen_s, 3.0)
        self.assertIsNone(session.messages[1].ttft_s)

        # Existing repo Codex fixture also produces samples
        existing = os.path.join(
            FIXTURES, "codex", "2026", "07", "01",
            "rollout-2026-07-01T01-00-03-019f1c0c-6a90-7281-b963-a5dab473915f.jsonl",
        )
        s2 = codex.parse_file(existing)
        self.assertEqual([m.gen_s for m in s2.messages], [3.488, 3.02, 9.296])

    def test_grok_fixture_produces_samples(self):
        usage_path = os.path.join(
            PERF_FIXTURES, "grok", "sessions",
            "%2FUsers%2Falice%2FDocuments%2FGitHub%2FFocusApp",
            "perf-grok-1", "usage.json",
        )
        session = grok.parse_file(usage_path)
        self.assertEqual(len(session.messages), 1)
        m = session.messages[0]
        self.assertEqual(m.model, "grok-4.6")
        self.assertEqual(m.output, 240)
        self.assertEqual(m.gen_s, 3.2)
        self.assertIsNone(m.ttft_s)

    def test_antigravity_protobuf_timing_and_response_tokens(self):
        tmp = tempfile.mkdtemp(prefix="kanjo-agy-perf-")
        self.addCleanup(shutil.rmtree, tmp, True)
        db_path = os.path.join(tmp, "agy-perf-1.db")
        ts_sec = 1794909600  # 2026-11-17T10:00:00Z
        # Build gen_metadata record:
        # 4={2: 100 (in), 3: 160 (out incl thinking), 5: 20 (cached), 9: 60 (thoughts)}
        # 9={4: {1: ts_sec}}, 11=ttft (0.75s), 12=stream (2.5s), 19="gemini-3-pro"
        usage_msg = (
            _pb_varint_field(2, 100)
            + _pb_varint_field(3, 160)
            + _pb_varint_field(5, 20)
            + _pb_varint_field(9, 60)
        )
        ts_msg = _pb_bytes(4, _pb_varint_field(1, ts_sec))
        gen_rec = (
            _pb_bytes(4, usage_msg)
            + _pb_bytes(9, ts_msg)
            + _pb_bytes(11, _pb_duration(0, 750_000_000))
            + _pb_bytes(12, _pb_duration(2, 500_000_000))
            + _pb_bytes(19, b"gemini-3-pro")
        )
        blob = _pb_bytes(1, gen_rec)

        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE trajectory_metadata_blob (data BLOB)")
        conn.execute("CREATE TABLE steps (idx INTEGER, step_type INTEGER, metadata BLOB, step_payload BLOB)")
        conn.execute("CREATE TABLE gen_metadata (idx INTEGER, data BLOB)")
        ws_blob = _pb_bytes(1, _pb_bytes(1, b"file:///Users/alice/Documents/GitHub/FocusApp"))
        conn.execute("INSERT INTO trajectory_metadata_blob VALUES (?)", (ws_blob,))
        conn.execute("INSERT INTO gen_metadata VALUES (0, ?)", (blob,))
        conn.commit()
        conn.close()

        session = antigravity.parse_file(db_path)
        self.assertEqual(len(session.messages), 1)
        m = session.messages[0]
        self.assertEqual(m.output, 160)
        self.assertEqual(m.thinking, 60)
        self.assertEqual(m.gen_s, 2.5)
        self.assertEqual(m.ttft_s, 0.75)

        # In export, Antigravity perf uses response-only tokens (160 - 60 = 100)
        fs = standard_fs()
        self.addCleanup(fs.cleanup)
        doc = build_export(
            dirs={"antigravity": [tmp]},
            fs_root=fs.root,
            home=ALICE,
            tokei_dir=NO_TOKEI,
            cache=None,
        )
        validate_contract(self, doc)
        rows = doc.get("perf_by_day") or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["agent"], "antigravity")
        self.assertEqual(rows[0]["model"], "gemini-3-pro")
        self.assertEqual(rows[0]["o"], 100)
        self.assertEqual(rows[0]["g"], 2.5)
        self.assertEqual(rows[0]["n"], 1)
        self.assertEqual(rows[0]["th"], {str(perf.ttft_bucket(0.75)): 1})


class ExportAndCachePerfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-perf-exp-")
        self.data_dir = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        os.makedirs(self.data_dir)
        os.makedirs(self.cache_dir)
        self.env = mock.patch.dict(os.environ, {
            "KANJO_DATA_DIR": self.data_dir,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_NO_NETWORK": "1",
        })
        self.env.start()
        self.fs = standard_fs()

    def tearDown(self):
        self.env.stop()
        self.fs.cleanup()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _perf_dirs(self):
        return {
            "claude": [os.path.join(PERF_FIXTURES, "claude")],
            "codex": [os.path.join(PERF_FIXTURES, "codex")],
            "grok": [os.path.join(PERF_FIXTURES, "grok", "sessions")],
        }

    def test_export_perf_by_day_sums_sorting_and_exclusions(self):
        cache = SessionCache(self.cache_dir)
        doc = build_export(
            dirs=self._perf_dirs(),
            fs_root=self.fs.root,
            home=ALICE,
            tokei_dir=NO_TOKEI,
            cache=cache,
        )
        validate_contract(self, doc)
        self.assertIn("perf_by_day", doc)
        rows = doc["perf_by_day"]
        # Sorted by (day, agent, model)
        self.assertEqual([(r["day"], r["agent"], r["model"]) for r in rows],
                         sorted((r["day"], r["agent"], r["model"]) for r in rows))
        by_agent = {r["agent"]: r for r in rows}
        self.assertEqual(set(by_agent), {"claude", "codex", "grok"})

        # Claude: 2 messages on same day & model -> summed o=250, g=9.0, n=2, 1 TTFT bucket (0.5s)
        c = by_agent["claude"]
        self.assertEqual(c["model"], "claude-opus-5-5")
        self.assertEqual(c["o"], 250)
        self.assertEqual(c["g"], 9.0)
        self.assertEqual(c["n"], 2)
        self.assertEqual(c["th"], {str(perf.ttft_bucket(0.5)): 1})

        # Codex: 2 messages -> o=320, g=7.0, n=2, 1 TTFT bucket (0.8s)
        x = by_agent["codex"]
        self.assertEqual(x["model"], "gpt-5.5")
        self.assertEqual(x["o"], 320)
        self.assertEqual(x["g"], 7.0)
        self.assertEqual(x["n"], 2)
        self.assertEqual(x["th"], {str(perf.ttft_bucket(0.8)): 1})

        # Grok: 1 message -> o=240, g=3.2, n=1, th={}
        g = by_agent["grok"]
        self.assertEqual(g["model"], "grok-4.6")
        self.assertEqual(g["o"], 240)
        self.assertEqual(g["g"], 3.2)
        self.assertEqual(g["n"], 1)
        self.assertEqual(g["th"], {})

        # Second run hitting AttributionCache + SessionCache produces identical perf_by_day
        cache2 = SessionCache(self.cache_dir)
        doc2 = build_export(
            dirs=self._perf_dirs(),
            fs_root=self.fs.root,
            home=ALICE,
            tokei_dir=NO_TOKEI,
            cache=cache2,
        )
        self.assertEqual(doc2["perf_by_day"], rows)

        # Absent in --mobile, --public-summary, --family-report
        mob = mobile_document(doc)
        self.assertNotIn("perf_by_day", mob)

        pub = build_public_summary(
            dirs=self._perf_dirs(),
            fs_root=self.fs.root,
            home=ALICE,
            cache=None,
        )
        self.assertNotIn("perf_by_day", pub)

        fam_cfg = Config(family_agents="all")
        fam = build_family_report(
            config=fam_cfg,
            dirs=self._perf_dirs(),
            fs_root=self.fs.root,
            home=ALICE,
            tokei_dir=NO_TOKEI,
            cache=None,
        )
        self.assertNotIn("perf_by_day", fam)

    def test_split_project_session_counted_once_not_split(self):
        # Session touches both FocusApp and tcf-canada equally (50/50 split)
        repo_a = GITHUB + "/FocusApp"
        repo_b = GITHUB + "/tcf-canada"
        s = Session(
            id="split-1",
            agent="claude",
            file="/x/split-1.jsonl",
            cwd=repo_a,
            messages=[
                Message(
                    ts=1794909605.0,
                    model="claude-opus-5-5",
                    input=100,
                    output=200,
                    cwd=repo_a,
                    key="split-1:m1",
                    gen_s=2.5,
                    ttft_s=0.4,
                )
            ],
            tool_paths=[[repo_a + "/a.py"], [repo_b + "/b.py"]],
        )
        s.note_time(1794909605.0)
        doc = build_export(
            fs_root=self.fs.root,
            home=ALICE,
            tokei_dir=NO_TOKEI,
            scan_result=ScanResult(sessions=[s], failed_files=[], stats={}),
        )
        # Verify the session really was split across 2 projects
        self.assertEqual(len(doc["projects"]), 2)
        self.assertEqual(doc["projects"][0]["sessions_detail"][0]["attribution"], "split")
        # perf_by_day counts the message once (o=200, n=1, not 2)
        self.assertEqual(len(doc["perf_by_day"]), 1)
        self.assertEqual(doc["perf_by_day"][0]["o"], 200)
        self.assertEqual(doc["perf_by_day"][0]["g"], 2.5)
        self.assertEqual(doc["perf_by_day"][0]["n"], 1)

    def test_absent_when_no_samples(self):
        s = Session(
            id="no-perf",
            agent="claude",
            file="/x/no-perf.jsonl",
            cwd=GITHUB + "/FocusApp",
            messages=[
                Message(ts=1794909605.0, model="claude-opus-5-5", input=10, output=5, gen_s=1.0),  # <20 out
                Message(ts=1794909606.0, model="claude-opus-5-5", input=10, output=50, gen_s=None),
            ],
        )
        s.note_time(1794909605.0)
        doc = build_export(
            fs_root=self.fs.root,
            home=ALICE,
            tokei_dir=NO_TOKEI,
            scan_result=ScanResult(sessions=[s], failed_files=[], stats={}),
        )
        self.assertNotIn("perf_by_day", doc)

    def test_cache_roundtrip_and_version_bump_and_legacy_ledger(self):
        self.assertGreaterEqual(CACHE_VERSION, 5)
        # Round-trip Message with gen_s and ttft_s (and one without)
        s = Session(
            id="rt-1",
            agent="claude",
            file="/x/rt-1.jsonl",
            messages=[
                Message(ts=1794909605.0, model="claude-opus-5-5", input=10, output=100,
                        key="k1", gen_s=2.345, ttft_s=0.678),
                Message(ts=1794909606.0, model="claude-opus-5-5", input=10, output=100,
                        key="k2", gen_s=1.5, ttft_s=None),
                Message(ts=1794909607.0, model="claude-opus-5-5", input=10, output=100,
                        key="k3"),
            ],
        )
        loaded = _load_session(_dump_session(s))
        self.assertEqual(loaded.messages[0].gen_s, 2.345)
        self.assertEqual(loaded.messages[0].ttft_s, 0.678)
        self.assertEqual(loaded.messages[1].gen_s, 1.5)
        self.assertIsNone(loaded.messages[1].ttft_s)
        self.assertIsNone(loaded.messages[2].gen_s)
        self.assertIsNone(loaded.messages[2].ttft_s)

        # Old v4 parse cache is ignored so files are re-parsed with timing
        old_cache = os.path.join(self.cache_dir, "parse-cache-v4.json")
        with open(old_cache, "w", encoding="utf-8") as fh:
            json.dump({"version": 4, "files": {}}, fh)
        cache = SessionCache(self.cache_dir)
        claude_path = os.path.join(
            PERF_FIXTURES, "claude", "-Users-alice-Documents-GitHub-FocusApp", "perf-claude-1.jsonl"
        )
        parsed = cache.get("claude", claude_path, None, claude.parse_file)
        self.assertEqual(parsed.messages[0].ttft_s, 0.5)
        cache.save()
        self.assertTrue(os.path.isfile(os.path.join(self.cache_dir, f"parse-cache-v{CACHE_VERSION}.json")))
        cache_reloaded = SessionCache(self.cache_dir)
        from_disk = cache_reloaded.get("claude", claude_path, None, lambda *_: self.fail("should hit cache"))
        self.assertEqual(from_disk.messages[0].gen_s, 4.0)
        self.assertEqual(from_disk.messages[0].ttft_s, 0.5)

        # Old 12-element ledger row (deleted log) loads fine with no timing and does not crash export
        ledger_path = os.path.join(self.data_dir, "ledger.json")
        legacy_row = {
            "version": 1,
            "updated_at": "2026-10-01T00:00:00Z",
            "entries": {
                "claude\0orphan-legacy\0": {
                    "source_path": "/deleted/orphan.jsonl",
                    "source_paths": ["/deleted/orphan.jsonl"],
                    "imported_at": "2026-10-01T00:00:00Z",
                    "file_sig": [[100, 1000], None],
                    "session": {
                        "id": "orphan-legacy",
                        "agent": "claude",
                        "file": "/deleted/orphan.jsonl",
                        "started": 1794909600.0,
                        "ended": 1794909605.0,
                        "cwd": GITHUB + "/FocusApp",
                        "messages": [
                            [1794909605.0, "claude-opus-5-5", 10, 80, 0, 0, 0, 0,
                             GITHUB + "/FocusApp", "main", "orphan:1", None]
                        ],
                    },
                }
            },
        }
        with open(ledger_path, "w", encoding="utf-8") as fh:
            json.dump(legacy_row, fh)
        doc = build_export(
            dirs={},
            fs_root=self.fs.root,
            home=ALICE,
            tokei_dir=NO_TOKEI,
        )
        validate_contract(self, doc)
        self.assertEqual(doc["totals"]["unique_sessions"], 1)
        self.assertNotIn("perf_by_day", doc)


if __name__ == "__main__":
    unittest.main()
