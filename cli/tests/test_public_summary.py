"""Tests for public usage summary and provider mappings (CONTRACT.md section 12)."""

import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

from kanjo import cli, export, providers
from tests.support import FIXTURE_DIRS, ensure_test_data_dir


class ProvidersTest(unittest.TestCase):
    def test_provider_labels(self):
        self.assertEqual(providers.PROVIDER_LABELS["anthropic"], "Anthropic")
        self.assertEqual(providers.PROVIDER_LABELS["openai"], "OpenAI")
        self.assertEqual(providers.PROVIDER_LABELS["google"], "Google")
        self.assertEqual(providers.PROVIDER_LABELS["xai"], "xAI")
        self.assertEqual(providers.PROVIDER_LABELS["alibaba"], "Alibaba (Qwen)")
        self.assertEqual(providers.PROVIDER_LABELS["minimax"], "MiniMax")
        self.assertEqual(providers.PROVIDER_LABELS["moonshot"], "Moonshot (Kimi)")
        self.assertEqual(providers.PROVIDER_LABELS["deepseek"], "DeepSeek")
        self.assertEqual(providers.PROVIDER_LABELS["zhipu"], "Zhipu (GLM)")
        self.assertEqual(providers.PROVIDER_LABELS["stepfun"], "StepFun")
        self.assertEqual(providers.PROVIDER_LABELS["other"], "Other")

    def test_all_provider_rules(self):
        # anthropic
        self.assertEqual(providers.provider_for("claude-3-5-sonnet", "claude"), "anthropic")
        self.assertEqual(providers.provider_for("claude-opus-4-8", "opencode"), "anthropic")

        # openai
        self.assertEqual(providers.provider_for("gpt-4o", "codex"), "openai")
        self.assertEqual(providers.provider_for("chatgpt-4o-latest", "commandcode"), "openai")
        self.assertEqual(providers.provider_for("codex-mini", "codex"), "openai")
        self.assertEqual(providers.provider_for("o1-preview", "pi"), "openai")
        self.assertEqual(providers.provider_for("o3-mini", "opencode"), "openai")

        # google
        self.assertEqual(providers.provider_for("gemini-1.5-pro", "antigravity"), "google")
        self.assertEqual(providers.provider_for("gemma-2-9b", "opencode"), "google")

        # xai
        self.assertEqual(providers.provider_for("grok-2", "grok"), "xai")
        self.assertEqual(providers.provider_for("grok-beta", "opencode"), "xai")

        # alibaba
        self.assertEqual(providers.provider_for("qwen-2.5-coder", "qwen"), "alibaba")
        self.assertEqual(providers.provider_for("qwq-32b", "opencode"), "alibaba")

        # minimax
        self.assertEqual(providers.provider_for("minimax-01", "minimax"), "minimax")
        self.assertEqual(providers.provider_for("abab6.5-chat", "opencode"), "minimax")

        # moonshot
        self.assertEqual(providers.provider_for("kimi-latest", "opencode"), "moonshot")
        self.assertEqual(providers.provider_for("moonshot-v1", "opencode"), "moonshot")

        # deepseek
        self.assertEqual(providers.provider_for("deepseek-chat", "opencode"), "deepseek")
        self.assertEqual(providers.provider_for("deepseek-reasoner", "pi"), "deepseek")

        # zhipu
        self.assertEqual(providers.provider_for("glm-4-plus", "opencode"), "zhipu")
        self.assertEqual(providers.provider_for("chatglm3-6b", "opencode"), "zhipu")

        # stepfun
        self.assertEqual(providers.provider_for("step-2-16k", "opencode"), "stepfun")
        self.assertEqual(providers.provider_for("step-1-8k", "pi"), "stepfun")

    def test_vendor_prefix_stripped(self):
        self.assertEqual(providers.provider_for("anthropic/claude-3-5-sonnet", "opencode"), "anthropic")
        self.assertEqual(providers.provider_for("openai/gpt-4o", "commandcode"), "openai")
        self.assertEqual(providers.provider_for("google/gemini-2.0-flash", "pi"), "google")
        self.assertEqual(providers.provider_for("deepseek/deepseek-coder", "opencode"), "deepseek")
        self.assertEqual(providers.provider_for("stepfun/step-1", "opencode"), "stepfun")

    def test_agent_fallback(self):
        # Single-vendor agents fallback to their provider
        self.assertEqual(providers.provider_for("custom-fine-tune", "claude"), "anthropic")
        self.assertEqual(providers.provider_for("custom-fine-tune", "codex"), "openai")
        self.assertEqual(providers.provider_for("custom-fine-tune", "antigravity"), "google")
        self.assertEqual(providers.provider_for("custom-fine-tune", "grok"), "xai")
        self.assertEqual(providers.provider_for("custom-fine-tune", "qwen"), "alibaba")
        self.assertEqual(providers.provider_for("custom-fine-tune", "minimax"), "minimax")

        # Multi-vendor agents have no fallback -> 'other'
        self.assertEqual(providers.provider_for("custom-fine-tune", "pi"), "other")
        self.assertEqual(providers.provider_for("custom-fine-tune", "opencode"), "other")
        self.assertEqual(providers.provider_for("custom-fine-tune", "commandcode"), "other")
        self.assertEqual(providers.provider_for("custom-fine-tune", "copilot"), "other")
        self.assertEqual(providers.provider_for("custom-fine-tune", "unknown_agent"), "other")

    def test_synthetic_model(self):
        self.assertEqual(providers.provider_for("<synthetic>", "claude"), "anthropic")
        self.assertEqual(providers.provider_for("<synthetic>", "pi"), "other")


class PublicSummaryExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="kanjo-pub-sum-test-")
        self.data_dir = os.path.join(self.tmp, "data")
        self.cache_dir = os.path.join(self.tmp, "cache")
        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)

        self.env = {
            "KANJO_DATA_DIR": self.data_dir,
            "KANJO_CACHE_DIR": self.cache_dir,
            "KANJO_CLAUDE_DIR": FIXTURE_DIRS["claude"][0],
            "KANJO_ANTIGRAVITY_DIR": FIXTURE_DIRS["antigravity"][0],
            "KANJO_CODEX_DIR": FIXTURE_DIRS["codex"][0],
            "KANJO_GROK_DIR": self.tmp,
            "KANJO_QWEN_DIR": self.tmp,
            "KANJO_COMMANDCODE_DIR": self.tmp,
            "KANJO_MINIMAX_DIR": self.tmp,
            "KANJO_OPENCODE_DIR": self.tmp,
            "KANJO_COPILOT_DIR": self.tmp,
            "KANJO_PI_DIR": self.tmp,
        }

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_cli(self, *args):
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.dict(os.environ, self.env), mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_public_summary_invariants_and_schema(self):
        code, out, err = self._run_cli("export", "--public-summary")
        self.assertEqual(code, 0, err)
        doc = json.loads(out)

        self.assertEqual(doc["schema_version"], 1)
        self.assertEqual(doc["kind"], "kanjo-public-summary")
        self.assertEqual(doc["currency"], "USD")
        self.assertIn("cost_note", doc)
        self.assertIn("all_time", doc)
        self.assertIn("months", doc)
        self.assertIn("weeks", doc)

        problems = export.check_public_summary_invariants(doc)
        self.assertEqual(problems, [], "Invariant violations: %s" % problems)

        # Check all_time period structure
        all_time = doc["all_time"]
        self.assertEqual(all_time["period"], "all")
        self.assertIn("tokens", all_time)
        self.assertIn("cost_usd", all_time)
        self.assertIn("by_provider", all_time)
        self.assertIn("by_agent", all_time)
        self.assertIn("top_models", all_time)

        # Provider tokens sum equals period tokens
        prov_tokens_total = sum(p["tokens"]["total"] for p in all_time["by_provider"])
        self.assertEqual(prov_tokens_total, all_time["tokens"]["total"])

        # Per-provider models invariants
        for p in all_time["by_provider"]:
            self.assertIn("models", p)
            self.assertLessEqual(len(p["models"]), 5)
            mod_tokens = sum(m["tokens_total"] for m in p["models"])
            self.assertLessEqual(mod_tokens, p["tokens"]["total"])
            for m in p["models"]:
                self.assertIn("model", m)
                self.assertIn("tokens_total", m)
                self.assertIn("cost_usd", m)

        # Agent tokens sum equals period tokens
        agent_tokens_total = sum(a["tokens_total"] for a in all_time["by_agent"])
        self.assertEqual(agent_tokens_total, all_time["tokens"]["total"])

        # Months and weeks sorting
        month_keys = [m["period"] for m in doc["months"]]
        self.assertEqual(month_keys, sorted(month_keys))

        week_keys = [w["period"] for w in doc["weeks"]]
        self.assertEqual(week_keys, sorted(week_keys))
        self.assertLessEqual(len(doc["weeks"]), 26)
        for w in doc["weeks"]:
            self.assertIn("start", w)
            self.assertRegex(w["start"], r"^\d{4}-\d{2}-\d{2}$")

    def test_privacy_guarantees(self):
        code, out, _ = self._run_cli("export", "--public-summary")
        self.assertEqual(code, 0)

        # Build full export to extract private identifiers present in fixtures
        full_doc = export.build_export(dirs={
            "claude": FIXTURE_DIRS["claude"],
            "antigravity": FIXTURE_DIRS["antigravity"],
            "codex": FIXTURE_DIRS["codex"],
        })

        private_strings = set()
        for p in full_doc["projects"]:
            if p.get("name"):
                private_strings.add(p["name"])
            if p.get("remote"):
                private_strings.add(p["remote"])
            for path in p.get("paths", []):
                private_strings.add(path)
            for s in p.get("sessions_detail", []):
                if s.get("id"):
                    private_strings.add(s["id"])
                if s.get("title"):
                    private_strings.add(s["title"])
                if s.get("cwd"):
                    private_strings.add(s["cwd"])
                if s.get("branch"):
                    private_strings.add(s["branch"])

        for b in full_doc["buckets"].values():
            for s in b.get("sessions_detail", []):
                if s.get("id"):
                    private_strings.add(s["id"])
                if s.get("title"):
                    private_strings.add(s["title"])
                if s.get("cwd"):
                    private_strings.add(s["cwd"])

        # Well-known fixture fragments
        known_fragments = [
            "/Users/", "FocusApp", "tcf-canada", "mammut001",
            "account", "email"
        ]

        out_lower = out.lower()
        for s in private_strings:
            if len(s) >= 4:
                self.assertNotIn(s.lower(), out_lower, "Private string leaked into public summary: %s" % s)

        for frag in known_fragments:
            self.assertNotIn(frag.lower(), out_lower, "Private fragment leaked into public summary: %s" % frag)

    def test_mutual_exclusivity(self):
        code, _, err = self._run_cli("export", "--public-summary", "--mobile")
        self.assertEqual(code, 2)
        self.assertIn("--public-summary cannot be combined with --mobile", err)

        code, _, err = self._run_cli("export", "--public-summary", "--hide-project-names")
        self.assertEqual(code, 2)
        self.assertIn("--hide-project-names requires --mobile", err)

    def test_fast_export_cache(self):
        code1, out1, _ = self._run_cli("export", "--public-summary")
        self.assertEqual(code1, 0)
        cache_file = os.path.join(self.cache_dir, "public-summary-last.json")
        self.assertTrue(os.path.isfile(cache_file))

        code2, out2, _ = self._run_cli("export", "--public-summary")
        self.assertEqual(code2, 0)
        self.assertEqual(out1, out2)

    def test_merged_model_variants_and_provider_models(self):
        from kanjo.pricing import PriceBook
        from kanjo.sources.base import Message, Session

        book = PriceBook()
        # Verify display names merge
        name1 = export._public_model_name("gemini-4-argon", "antigravity", book)
        name2 = export._public_model_name("gemini-4-argon-trial", "antigravity", book)
        name3 = export._public_model_name("gemini-4-argon-s", "antigravity", book)
        self.assertEqual(name1, "gemini-4-argon")
        self.assertEqual(name2, "gemini-4-argon")
        self.assertEqual(name3, "gemini-4-argon")

        # Unknown model variant suffixes
        unknown_high = export._public_model_name("custom-model-high", "unknown", book)
        unknown_thinking = export._public_model_name("custom-model-thinking", "unknown", book)
        self.assertEqual(unknown_high, "custom-model")
        self.assertEqual(unknown_thinking, "custom-model")

        # Create session with multiple Argon variants
        s = Session(id="test-argon-merge", agent="antigravity", file="/path/test.db")
        s.messages = [
            Message(ts=1793500000.0, model="gemini-4-argon", input=1000, output=500),
            Message(ts=1793500100.0, model="gemini-4-argon-trial", input=2000, output=1000),
            Message(ts=1793500200.0, model="gemini-4-argon-s", input=3000, output=1500),
        ]
        scan_res = export.ScanResult(sessions=[s], failed_files=[], stats={})
        summary = export.build_public_summary(prices=book, scan_result=scan_res)

        google_prov = next(p for p in summary["all_time"]["by_provider"] if p["provider"] == "google")
        argon_models = [m for m in google_prov["models"] if m["model"] == "gemini-4-argon"]
        self.assertEqual(len(argon_models), 1)
        self.assertEqual(argon_models[0]["tokens_total"], (1000 + 500) + (2000 + 1000) + (3000 + 1500))

        top_argon = [m for m in summary["all_time"]["top_models"] if m["model"] == "gemini-4-argon"]
        self.assertEqual(len(top_argon), 1)
        self.assertEqual(top_argon[0]["tokens_total"], argon_models[0]["tokens_total"])

    def test_models_used_lists_every_model_beyond_top_models_cap(self):
        from kanjo.pricing import PriceBook
        from kanjo.sources.base import Message, Session

        names = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "gpt-5.5",
                 "gpt-5-mini", "gemini-3.8-flash", "grok-4.7-build", "qwen3.8-max",
                 "deepseek-v4-flash", "kimi-k2.7", "glm-5.2", "minimax-m3"]
        s = Session(id="many-models", agent="opencode", file="/path/many.db")
        s.messages = [Message(ts=1793500000.0 + i * 60, model=name, input=1000 + i, output=100)
                      for i, name in enumerate(names)]
        scan_res = export.ScanResult(sessions=[s], failed_files=[], stats={})
        summary = export.build_public_summary(prices=PriceBook(), scan_result=scan_res)

        for period in [summary["all_time"]] + summary["months"] + summary["weeks"]:
            self.assertEqual(len(period["top_models"]), 8)
            self.assertEqual(len(period["models_used"]), len(names))
            self.assertEqual(period["models_used"], sorted(period["models_used"]))
            self.assertTrue({m["model"] for m in period["top_models"]} <= set(period["models_used"]))
        self.assertEqual(export.check_public_summary_invariants(summary), [])

        summary["all_time"]["models_used"] = summary["all_time"]["models_used"][:3]
        problems = export.check_public_summary_invariants(summary)
        self.assertTrue(any("not in models_used" in p for p in problems))

    def test_provider_models_invariant_check(self):
        code, out, _ = self._run_cli("export", "--public-summary")
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(export.check_public_summary_invariants(doc), [])

        # Corrupt a provider models tokens_total to exceed provider tokens.total
        corrupt = json.loads(out)
        prov = corrupt["all_time"]["by_provider"][0]
        if prov["models"]:
            prov["models"][0]["tokens_total"] = prov["tokens"]["total"] + 1000
            problems = export.check_public_summary_invariants(corrupt)
            self.assertTrue(any("models tokens_total sum" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
