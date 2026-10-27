"""Shared test helpers: a fake filesystem with git repos, and a CONTRACT.md validator."""

import os
import re
import shutil
import tempfile
from datetime import datetime, timedelta


def ensure_test_data_dir():
    """Keep the permanent ledger off the real home directory during tests."""
    os.environ.setdefault("KANJO_NO_NETWORK", "1")
    current = os.environ.get("KANJO_DATA_DIR", "")
    home = os.path.abspath(os.path.expanduser("~"))
    if current:
        absolute = os.path.abspath(os.path.expanduser(current))
        if absolute != home and not absolute.startswith(home + os.sep):
            return
    os.environ["KANJO_DATA_DIR"] = tempfile.mkdtemp(prefix="kanjo-test-data-")


ensure_test_data_dir()

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, "fixtures")
FIXTURE_DIRS = {
    "claude": [os.path.join(FIXTURES, "claude")],
    "antigravity": [os.path.join(FIXTURES, "antigravity")],
    "codex": [os.path.join(FIXTURES, "codex")],
}
ALICE = "/Users/alice"
GITHUB = ALICE + "/Documents/GitHub"


class FakeFS:
    """A temp directory standing in for "/" (passed to Resolver as fs_root)."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="kanjo-test-")

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def real(self, path):
        return self.root + path

    def mkdir(self, path):
        os.makedirs(self.real(path), exist_ok=True)
        return path

    def write(self, path, text):
        os.makedirs(os.path.dirname(self.real(path)), exist_ok=True)
        with open(self.real(path), "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def repo(self, path, remotes=None):
        """remotes: list of (name, url)."""
        self.mkdir(path + "/.git")
        config = "[core]\n\trepositoryformatversion = 0\n"
        for name, url in remotes or []:
            config += '[remote "%s"]\n\turl = %s\n\tfetch = +refs/heads/*:refs/remotes/%s/*\n' % (name, url, name)
        self.write(path + "/.git/config", config)
        return path

    def worktree(self, main, path, name=None, create_dir=True, admin=True):
        """A linked worktree of ``main``. admin=False simulates `git worktree prune`;
        create_dir=False simulates a deleted worktree directory that is still registered."""
        name = name or os.path.basename(path)
        admin_dir = main + "/.git/worktrees/" + name
        if admin:
            self.write(admin_dir + "/gitdir", path + "/.git\n")
            self.write(admin_dir + "/commondir", "../..\n")
        if create_dir:
            self.write(path + "/.git", "gitdir: %s\n" % admin_dir)
        return path


def standard_fs():
    """Repos matching the fixture logs."""
    fs = FakeFS()
    fs.repo(GITHUB + "/FocusApp", [("origin", "https://github.com/alice/FocusApp.git")])
    # the Claude scratchpad worktree used by an Antigravity fixture session, since deleted
    fs.worktree(GITHUB + "/FocusApp",
                "/private/tmp/claude-501/-Users-alice-Documents-GitHub-FocusApp/"
                "928ec0a9-8451-40d6-9f13-8bc49461b9b5/scratchpad/redesign", create_dir=False)
    fs.repo(GITHUB + "/tcf-canada")  # no remote
    fs.mkdir(ALICE + "/Downloads")
    return fs


# ---- contract validation -----------------------------------------------------------
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TOKEN_KEYS = {"input", "output", "cache_read", "cache_write", "thinking", "total"}
AGG_KEYS = {"cost", "tokens", "sessions", "first_active", "last_active"}
SESSION_KEYS = {"id", "agent", "label", "started", "ended", "cwd", "branch", "models", "cost",
                "tokens", "share", "attribution", "subagents", "title"}
PROJECT_KINDS = {"dominant", "split", "cwd", "scratchpad", "override"}
COST_NOTE = "API-equivalent cost estimated from public API prices. Not actual subscription spend."


def _check_tokens(tc, t, where):
    tc.assertTrue(TOKEN_KEYS <= set(t), where)
    for k in TOKEN_KEYS:
        tc.assertIsInstance(t[k], int, "%s.%s" % (where, k))
        tc.assertGreaterEqual(t[k], 0, "%s.%s" % (where, k))
    tc.assertEqual(t["total"], t["input"] + t["output"] + t["cache_read"] + t["cache_write"], where)


def _check_cost(tc, v, where):
    tc.assertIsInstance(v, (int, float), where)
    tc.assertEqual(round(v, 4), v, where + " has more than 4 decimals")
    tc.assertGreaterEqual(v, 0, where)


def _check_agg(tc, a, where):
    tc.assertTrue(AGG_KEYS <= set(a), "%s missing %s" % (where, AGG_KEYS - set(a)))
    _check_cost(tc, a["cost"], where + ".cost")
    _check_tokens(tc, a["tokens"], where + ".tokens")
    tc.assertIsInstance(a["sessions"], int)
    for k in ("first_active", "last_active"):
        tc.assertTrue(a[k] is None or DAY.match(a[k]), "%s.%s" % (where, k))
    if a["first_active"] and a["last_active"]:
        tc.assertLessEqual(a["first_active"], a["last_active"])


def _check_session(tc, s, where, kinds, share_one=False):
    tc.assertTrue(SESSION_KEYS <= set(s), "%s missing %s" % (where, SESSION_KEYS - set(s)))
    tc.assertIn(s["attribution"], kinds, where)
    tc.assertRegex(s["started"], ISO_UTC)
    tc.assertRegex(s["ended"], ISO_UTC)  # required
    tc.assertLessEqual(s["started"], s["ended"])
    tc.assertTrue(0 < s["share"] <= 1, where)
    if share_one:
        tc.assertEqual(s["share"], 1)
    if s["attribution"] == "split":
        tc.assertLess(s["share"], 1, where)
    _check_cost(tc, s["cost"], where + ".cost")
    _check_tokens(tc, s["tokens"], where + ".tokens")
    tc.assertIsInstance(s["models"], list)
    tc.assertIsInstance(s["subagents"], int)
    tc.assertTrue(s["title"] is None or len(s["title"]) <= 80)
    tc.assertTrue(s["cwd"] is None or isinstance(s["cwd"], str))


QUOTA_KEYS = {"weekly_resets_at", "weekly_window_hours", "weekly_used_percent", "five_hour_resets_at",
              "five_hour_window_hours", "five_hour_used_percent", "source"}
SUBSCRIPTION_KEYS = {"plan", "plan_label", "monthly_price_usd", "cycle_start", "cycle_end",
                     "anchor_day", "cycle_source", "extra_usage_enabled", "source"}
CYCLE_SOURCES = {"subscription_date", "rolling_30d", "manual"}
SUBSCRIPTION_SOURCES = {"detected", "manual"}


def check_quota_windows(tc, qw):
    tc.assertIsInstance(qw, dict, "quota_windows")
    for agent, w in qw.items():
        where = "quota_windows.%s" % agent
        tc.assertEqual(set(w) - {"extra_windows"}, QUOTA_KEYS, where)
        if "extra_windows" in w:
            tc.assertIsInstance(w["extra_windows"], list, where)
            for ew in w["extra_windows"]:
                tc.assertIn("id", ew)
                tc.assertIn("title", ew)
        tc.assertRegex(w["weekly_resets_at"], ISO_UTC)
        tc.assertIsInstance(w["weekly_window_hours"], int, where)
        tc.assertNotIsInstance(w["weekly_window_hours"], bool, where)
        tc.assertGreater(w["weekly_window_hours"], 0, where)
        tc.assertTrue(w["five_hour_resets_at"] is None or ISO_UTC.match(w["five_hour_resets_at"]), where)
        tc.assertIn(w["source"], {"tokei", "manual"}, where)
        if w["five_hour_resets_at"] is not None:
            tc.assertIsInstance(w["five_hour_window_hours"], int, where)
        if w["five_hour_resets_at"] is None:
            tc.assertIsNone(w["five_hour_used_percent"], where)
        for key in ("weekly_used_percent", "five_hour_used_percent"):
            pct = w[key]
            tc.assertTrue(pct is None or (isinstance(pct, float) and 0 <= pct <= 100), where)


def check_subscriptions(tc, subs):
    tc.assertIsInstance(subs, dict, "subscriptions")
    for agent, sub in subs.items():
        where = "subscriptions.%s" % agent
        tc.assertIsInstance(sub, dict, where)
        tc.assertEqual(set(sub), SUBSCRIPTION_KEYS, where)
        tc.assertIsInstance(sub["plan"], str, where)
        tc.assertTrue(sub["plan"], where + " plan")
        tc.assertIsInstance(sub["plan_label"], str, where)
        tc.assertTrue(sub["plan_label"], where + " plan_label")
        price = sub["monthly_price_usd"]
        if price is not None:
            tc.assertIsInstance(price, (int, float), where + " monthly_price_usd")
            tc.assertNotIsInstance(price, bool, where + " monthly_price_usd")
        tc.assertRegex(sub["cycle_start"], ISO_UTC, where)
        tc.assertRegex(sub["cycle_end"], ISO_UTC, where)
        tc.assertLess(sub["cycle_start"], sub["cycle_end"], where)
        tc.assertIn(sub["cycle_source"], CYCLE_SOURCES, where)
        if sub["cycle_source"] == "rolling_30d":
            tc.assertIsNone(sub["anchor_day"], where)
            start = datetime.fromisoformat(sub["cycle_start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(sub["cycle_end"].replace("Z", "+00:00"))
            tc.assertEqual(end - start, timedelta(days=30), where)
        else:
            tc.assertIsInstance(sub["anchor_day"], int, where)
            tc.assertNotIsInstance(sub["anchor_day"], bool, where)
            tc.assertGreaterEqual(sub["anchor_day"], 1, where)
            tc.assertLessEqual(sub["anchor_day"], 31, where)
        tc.assertIsInstance(sub["extra_usage_enabled"], bool, where)
        tc.assertIn(sub["source"], SUBSCRIPTION_SOURCES, where)


def _desc(seq):
    return all(a >= b for a, b in zip(seq, seq[1:]))


LEDGER_KEYS = {"path", "sessions", "orphaned", "updated_at"}


def check_ledger(tc, ledger):
    """CONTRACT.md section 9. The field is optional so older sample files still pass."""
    tc.assertIsInstance(ledger, dict, "ledger")
    tc.assertTrue(LEDGER_KEYS <= set(ledger), "ledger missing %s" % (LEDGER_KEYS - set(ledger)))
    tc.assertIsInstance(ledger["path"], str)
    tc.assertTrue(ledger["path"].endswith("ledger.json"), ledger["path"])
    tc.assertIsInstance(ledger["sessions"], int)
    tc.assertNotIsInstance(ledger["sessions"], bool)
    tc.assertGreaterEqual(ledger["sessions"], 0)
    tc.assertIsInstance(ledger["orphaned"], int)
    tc.assertNotIsInstance(ledger["orphaned"], bool)
    tc.assertGreaterEqual(ledger["orphaned"], 0)
    tc.assertLessEqual(ledger["orphaned"], ledger["sessions"])
    for key in ("empty", "errors"):
        if key in ledger:
            tc.assertIsInstance(ledger[key], int, key)
            tc.assertNotIsInstance(ledger[key], bool, key)
            tc.assertGreaterEqual(ledger[key], 0, key)
    tc.assertRegex(ledger["updated_at"], ISO_UTC)


def validate_contract(tc, doc):
    """Assert that ``doc`` follows CONTRACT.md (structure, ordering, invariants)."""
    for k in ("schema_version", "generated_at", "generated_by", "timezone", "currency", "cost_note",
              "config", "quota_windows", "subscriptions", "totals", "projects", "buckets"):
        tc.assertIn(k, doc)
    tc.assertEqual(doc["schema_version"], 1)
    tc.assertRegex(doc["generated_at"], ISO_UTC)
    tc.assertTrue(doc["generated_by"].startswith("kanjo "))
    tc.assertRegex(doc["timezone"], r"^[A-Za-z_]+(/[A-Za-z0-9_+\-]+)*$")
    tc.assertEqual(doc["currency"], "USD")
    tc.assertEqual(doc["cost_note"], COST_NOTE)
    tc.assertIsInstance(doc["config"]["dominant_threshold"], (int, float))
    check_quota_windows(tc, doc["quota_windows"])
    check_subscriptions(tc, doc["subscriptions"])

    _check_agg(tc, doc["totals"], "totals")
    tc.assertIn("unique_sessions", doc["totals"])
    b = doc["buckets"]
    for name, kind in (("unattributed", "none"), ("excluded", "excluded")):
        _check_agg(tc, b[name], name)
        for s in b[name]["sessions_detail"]:
            _check_session(tc, s, name, {kind}, share_one=True)
        tc.assertEqual(len(b[name]["sessions_detail"]), b[name]["sessions"])
    tc.assertEqual(b["parse_failed"]["sessions"], len(b["parse_failed"]["files"]))

    projects = doc["projects"]
    tc.assertTrue(_desc([p["cost"] for p in projects]), "projects not sorted by cost desc")
    ids = [p["id"] for p in projects]
    tc.assertEqual(len(ids), len(set(ids)), "duplicate project ids")
    for p in projects:
        where = "project %s" % p["id"]
        _check_agg(tc, p, where)
        for k in ("id", "name", "remote", "paths", "path_missing", "by_agent", "by_model", "by_day",
                  "by_branch", "sessions_detail"):
            tc.assertIn(k, p, where)
        if p["remote"] is not None:
            tc.assertEqual(p["id"], p["remote"])
        else:
            tc.assertTrue(p["id"].startswith("/"), where)
        if p["path_missing"]:
            tc.assertIsNone(p["remote"], where)  # unless aliased; tests do not alias these
        tc.assertTrue(_desc([a["cost"] for a in p["by_agent"]]), where + " by_agent order")
        tc.assertTrue(_desc([m["cost"] for m in p["by_model"]]), where + " by_model order")
        tc.assertTrue(_desc([x["cost"] for x in p["by_branch"]]), where + " by_branch order")
        days = [d["day"] for d in p["by_day"]]
        tc.assertEqual(days, sorted(set(days)), where + " by_day must be ascending and unique")
        for d in p["by_day"]:
            tc.assertRegex(d["day"], DAY)
            tc.assertIsInstance(d["tokens"], int)
            tc.assertIsInstance(d["by_agent"], dict, where + " by_day.by_agent")
            tc.assertTrue(d["by_agent"], where + " by_day.by_agent must not be empty")
            tc.assertLessEqual(set(d["by_agent"]), {a["agent"] for a in p["by_agent"]}, where)
            tc.assertAlmostEqual(sum(d["by_agent"].values()), d["cost"], delta=0.01, msg=where + " " + d["day"])
            tc.assertIsInstance(d["by_agent_tokens"], dict, where + " by_day.by_agent_tokens")
            tc.assertEqual(set(d["by_agent_tokens"]), set(d["by_agent"]), where + " " + d["day"])
            for v in d["by_agent_tokens"].values():
                tc.assertIsInstance(v, int, where + " by_agent_tokens")
                tc.assertGreaterEqual(v, 0, where + " by_agent_tokens")
            tc.assertEqual(sum(d["by_agent_tokens"].values()), d["tokens"], where + " " + d["day"])
        for a in p["by_agent"]:
            tc.assertTrue({"agent", "label", "cost", "tokens", "sessions"} <= set(a))
            _check_tokens(tc, a["tokens"], where + " by_agent")
        for m in p["by_model"]:
            tc.assertTrue({"model", "agent", "cost", "tokens", "estimated"} <= set(m))
            tc.assertIsInstance(m["estimated"], bool)
        for x in p["by_branch"]:
            tc.assertTrue({"branch", "cost", "sessions"} <= set(x))
        if p["by_branch"]:
            tc.assertTrue(any(x["branch"] != "(unknown)" for x in p["by_branch"]),
                          where + ": by_branch must be [] when no session has a branch")
        started = [s["started"] for s in p["sessions_detail"]]
        tc.assertEqual(started, sorted(started, reverse=True), where + " sessions_detail order")
        tc.assertEqual(len(p["sessions_detail"]), p["sessions"])
        for s in p["sessions_detail"]:
            _check_session(tc, s, where, PROJECT_KINDS)
        tc.assertAlmostEqual(sum(s["cost"] for s in p["sessions_detail"]), p["cost"], delta=0.01)
        tc.assertEqual(sum(a["sessions"] for a in p["by_agent"]), p["sessions"])

    # reconciliation invariant
    parts = projects + [b["unattributed"], b["excluded"]]
    tc.assertAlmostEqual(doc["totals"]["cost"], sum(x["cost"] for x in parts), delta=0.01)
    for k in TOKEN_KEYS:
        tc.assertEqual(doc["totals"]["tokens"][k], sum(x["tokens"][k] for x in parts), "tokens." + k)
    tc.assertEqual(doc["totals"]["sessions"], sum(x["sessions"] for x in parts))
    tc.assertLessEqual(doc["totals"]["unique_sessions"], doc["totals"]["sessions"])
    if "ledger" in doc:
        check_ledger(tc, doc["ledger"])
