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


if __name__ == "__main__":
    unittest.main()
