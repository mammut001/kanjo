"""Schema check: real fixture export / mobile / disk JSON match CONTRACT.md required fields.

Cannot decode with the Mac Swift decoder from Python; instead assert every required
field listed in CONTRACT.md for the report, mobile, and disk formats.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from tests.support import (
    FIXTURES,
    validate_contract,
    validate_disk_schema,
    validate_mobile_schema,
)

CLI_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NO_TOKEI = os.path.join(FIXTURES, "no-tokei")
PATHSEP = os.pathsep


def _fixture_env(data_dir: str, cache_dir: str, config_dir: str) -> dict:
    """Every KANJO_*_DIR → cli/tests/fixtures; Kanjo dirs → throwaway temps."""
    env = dict(os.environ)
    env["KANJO_NO_NETWORK"] = "1"
    env["KANJO_DATA_DIR"] = data_dir
    env["KANJO_CACHE_DIR"] = cache_dir
    env["KANJO_CONFIG_DIR"] = config_dir
    env["KANJO_TRASH_DIR"] = os.path.join(data_dir, "trash")
    env["KANJO_SCRATCH_DIR"] = os.path.join(data_dir, "scratch")
    env["KANJO_TOKEI_DIR"] = NO_TOKEI
    env["KANJO_CLAUDE_APP_CACHE"] = os.path.join(data_dir, "claude-app")
    env["KANJO_CLAUDE_CONFIG"] = os.path.join(data_dir, "no-claude.json")
    env["KANJO_CODEX_AUTH"] = os.path.join(data_dir, "no-codex-auth.json")
    env["KANJO_GROK_AUTH"] = os.path.join(data_dir, "no-grok-auth.json")
    os.makedirs(env["KANJO_TRASH_DIR"], exist_ok=True)
    os.makedirs(env["KANJO_SCRATCH_DIR"], exist_ok=True)
    os.makedirs(env["KANJO_CLAUDE_APP_CACHE"], exist_ok=True)

    mapping = {
        "KANJO_CLAUDE_DIR": "claude",
        "KANJO_ANTIGRAVITY_DIR": "antigravity",
        "KANJO_CODEX_DIR": "codex",
        "KANJO_GROK_DIR": "grok",
        "KANJO_QWEN_DIR": "qwen",
        "KANJO_COMMANDCODE_DIR": "commandcode",
        "KANJO_MINIMAX_DIR": "minimax",
        "KANJO_OPENCODE_DIR": "opencode",
        "KANJO_PI_DIR": "pi",
        "KANJO_WORKBUDDY_DIR": "workbuddy",
        "KANJO_WORKBUDDY_AI_DIR": "workbuddy_ai",
        "KANJO_CODEBUDDY_DIR": "codebuddy",
        "KANJO_QWENWORK_DIR": "qwenwork",
        "KANJO_GROK_BOT_DIR": "grok_bot",
        "KANJO_QODERWORK_DIR": "qoderwork",
        "KANJO_QODERCLI_DIR": "qodercli",
        "KANJO_QODERCLI_CN_DIR": "qodercli_cn",
        "KANJO_ZCODE_DIR": "zcode",
        "KANJO_KIMICODE_DIR": "kimicode",
        "KANJO_MUSECODE_DIR": "musecode",
        "KANJO_QODER_IDE_DIR": "qoder_ide",
        "KANJO_HERMES_DIR": "hermes",
        "KANJO_OPENCLAW_DIR": "openclaw",
        "KANJO_DEVIN_DIR": "devin",
        "KANJO_MIMOCODE_DIR": "mimocode",
        "KANJO_PRIME_AGENT_DIR": "prime_agent",
        "KANJO_OMP_DIR": "omp",
        "KANJO_DEEPSEEK_HARNESS_DIR": "deepseek_harness",
    }
    for var, name in mapping.items():
        env[var] = os.path.join(FIXTURES, name)
    env["KANJO_COPILOT_DIR"] = PATHSEP.join(
        os.path.join(FIXTURES, name) for name in ("copilot", "copilot_db")
    )
    return env


class FixtureExportSchemaTest(unittest.TestCase):
    """Run the real CLI on fixtures and assert CONTRACT.md schemas."""

    @classmethod
    def setUpClass(cls):
        cls.data_dir = tempfile.mkdtemp(prefix="kanjo-e2e-schema-data-")
        cls.cache_dir = tempfile.mkdtemp(prefix="kanjo-e2e-schema-cache-")
        cls.config_dir = tempfile.mkdtemp(prefix="kanjo-e2e-schema-config-")
        cls.env = _fixture_env(cls.data_dir, cls.cache_dir, cls.config_dir)
        cls.report = cls._run_json(["export"])
        cls.mobile = cls._run_json(["export", "--mobile"])
        cls.disk = cls._run_json(["disk", "--json"], stdout_only=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.data_dir, ignore_errors=True)
        shutil.rmtree(cls.cache_dir, ignore_errors=True)
        shutil.rmtree(cls.config_dir, ignore_errors=True)

    @classmethod
    def _run_json(cls, argv, stdout_only=False):
        proc = subprocess.run(
            [sys.executable, "-m", "kanjo"] + argv,
            cwd=CLI_DIR,
            capture_output=True,
            env=cls.env,
        )
        if proc.returncode != 0:
            raise AssertionError(
                "kanjo %s failed (%d): %s"
                % (" ".join(argv), proc.returncode, proc.stderr.decode("utf-8", "replace"))
            )
        raw = proc.stdout
        return json.loads(raw.decode("utf-8"))

    def test_report_matches_contract(self):
        validate_contract(self, self.report)
        self.assertIn("ledger", self.report)

    def test_mobile_matches_contract_section_11(self):
        validate_mobile_schema(self, self.mobile)
        # Numbers agree with the full export (CONTRACT: same values, trimmed fields).
        self.assertEqual(self.mobile["totals"]["cost"], self.report["totals"]["cost"])
        self.assertEqual(self.mobile["totals"]["tokens"], self.report["totals"]["tokens"])
        self.assertEqual(len(self.mobile["projects"]), len(self.report["projects"]))

    def test_disk_matches_contract_section_10(self):
        validate_disk_schema(self, self.disk)


if __name__ == "__main__":
    unittest.main()
