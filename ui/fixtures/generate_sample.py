"""Generate ui/fixtures/sample.json following CONTRACT.md, bottom-up so invariants hold.

Usage: python3 fixtures/generate_sample.py [out.json]   (default: fixtures/sample.json)
Deterministic (seeded). Edit SPECS to change projects; invariants are asserted at the end.
"""
import json, random, uuid, sys
from datetime import datetime, timedelta, timezone

rnd = random.Random(42)
LOCAL = timezone(timedelta(hours=8))
LABELS = {"claude": "Claude Code", "antigravity": "Antigravity CLI", "codex": "Codex CLI"}
# per Mtok: input, output, cache_read, cache_write ; estimated flag
PRICES = {
    "claude-opus-5-5":        (15, 75, 1.5, 18.75, False),
    "claude-sonnet-5":        (3, 15, 0.3, 3.75, False),
    "claude-haiku-5-5":       (1, 5, 0.1, 1.25, False),
    "claude-opus-5-6-preview":(15, 75, 1.5, 18.75, True),
    "gemini-3-pro":           (2, 12, 0.2, 0.5, False),
    "gemini-3-flash":         (0.3, 2.5, 0.03, 0.1, False),
    "gemini-3.5-pro-exp":     (2.5, 15, 0.25, 0.6, True),
    "gpt-5.5-codex":          (1.25, 10, 0.125, 0, False),
    "gpt-5.5-mini":           (0.25, 2, 0.025, 0, False),
}
AGENT_MODELS = {
    "claude": [["claude-opus-5-5"], ["claude-opus-5-5", "claude-haiku-5-5"], ["claude-sonnet-5"], ["claude-sonnet-5", "claude-haiku-5-5"]],
    "antigravity": [["gemini-3-pro"], ["gemini-3-pro", "gemini-3-flash"], ["gemini-3-flash"]],
    "codex": [["gpt-5.5-codex"], ["gpt-5.5-codex", "gpt-5.5-mini"]],
}
TITLES = [
    "fix quota reset after midnight rollover", "add widget refresh on app foreground",
    "why does the build fail on CI but not locally?", "refactor settings store into separate module",
    "write tests for the paywall flow", "bump deps and fix breaking changes", None,
    "investigate memory leak in timeline view", "implement CSV export", "review this diff",
    "migrate config to toml", "add dark mode support", "<script>alert('xss in title')</script> sanitize test",
    "port parser to streaming JSONL reader", "explain this stack trace", None,
    "speed up cold start by lazy loading fonts", "rename package and update imports",
    "set up release workflow with signing", "draft README for the new CLI flags",
]

def toks(scale):
    inp = int(rnd.uniform(2e3, 3e4) * scale)
    out = int(rnd.uniform(3e3, 4e4) * scale)
    cr = int(rnd.uniform(1e5, 2.5e6) * scale)
    cw = int(rnd.uniform(1e4, 2e5) * scale)
    return [inp, out, cr, cw]

def cost_of(model, t):
    p = PRICES[model]
    return (t[0]*p[0] + t[1]*p[1] + t[2]*p[2] + t[3]*p[3]) / 1e6

def make_raw_session(agent, start, cwd, branch, scale=1.0, models=None):
    models = models or rnd.choice(AGENT_MODELS[agent])
    dur = timedelta(minutes=rnd.randint(4, 180))
    per_model = {}
    for i, m in enumerate(models):
        t = toks(scale * (1.0 if i == 0 else 0.25))
        think_ratio = {"claude": 0.3, "antigravity": 0.45, "codex": 0.0}[agent]
        think = int(t[1] * think_ratio * rnd.uniform(0.5, 1))
        per_model[m] = t + [think]
    return {
        "id": str(uuid.UUID(int=rnd.getrandbits(128))), "agent": agent,
        "started": start, "ended": start + dur, "cwd": cwd, "branch": branch,
        "models": models, "per_model": per_model,
        "subagents": rnd.choice([0, 0, 0, 1, 2, 3]) if agent == "claude" else 0,
        "title": rnd.choice(TITLES),
    }

def tok_obj(t):
    return {"input": t[0], "output": t[1], "cache_read": t[2], "cache_write": t[3],
            "thinking": t[4], "total": t[0]+t[1]+t[2]+t[3]}

def portion(raw, share, attribution):
    """Return session row (contract Session) plus per-model scaled tokens/cost."""
    pm = {}
    for m, t in raw["per_model"].items():
        st = [round(x * share) for x in t]
        pm[m] = (st, cost_of(m, st))
    tt = [sum(v[0][i] for v in pm.values()) for i in range(5)]
    cost = sum(v[1] for v in pm.values())
    row = {
        "id": raw["id"], "agent": raw["agent"], "label": LABELS[raw["agent"]],
        "started": raw["started"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended": raw["ended"].strftime("%Y-%m-%dT%H:%M:%SZ"),
        "cwd": raw["cwd"], "branch": raw["branch"], "models": raw["models"],
        "cost": round(cost, 4), "tokens": tok_obj(tt), "share": share,
        "attribution": attribution, "subagents": raw["subagents"], "title": raw["title"],
    }
    return row, pm

def local_day(dt):
    return dt.astimezone(LOCAL).strftime("%Y-%m-%d")

def add_t(a, b):
    for k in a: a[k] += b[k]

def zero_t():
    return {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "thinking": 0, "total": 0}

def aggregate(rows_pm):
    cost = sum(r["cost"] for r, _ in rows_pm)
    t = zero_t()
    for r, _ in rows_pm: add_t(t, r["tokens"])
    days = sorted(local_day(datetime.strptime(r["started"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)) for r, _ in rows_pm)
    return {"cost": round(cost, 4), "tokens": t, "sessions": len(rows_pm),
            "first_active": days[0] if days else None, "last_active": days[-1] if days else None}

def build_project(pid, name, remote, paths, path_missing, rows_pm):
    agg = aggregate(rows_pm)
    by_agent, by_model, by_day, by_branch = {}, {}, {}, {}
    for r, pm in rows_pm:
        a = by_agent.setdefault(r["agent"], {"agent": r["agent"], "label": r["label"], "cost": 0.0, "tokens": zero_t(), "sessions": 0})
        a["cost"] += r["cost"]; add_t(a["tokens"], r["tokens"]); a["sessions"] += 1
        for m, (st, c) in pm.items():
            bm = by_model.setdefault(m, {"model": m, "agent": r["agent"], "cost": 0.0, "tokens": zero_t(), "estimated": PRICES[m][4]})
            bm["cost"] += c; add_t(bm["tokens"], tok_obj(st))
        d = local_day(datetime.strptime(r["started"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc))
        bd = by_day.setdefault(d, {"day": d, "cost": 0.0, "tokens": 0, "by_agent": {}, "by_agent_tokens": {}})
        bd["cost"] += r["cost"]; bd["tokens"] += r["tokens"]["total"]
        bd["by_agent"][r["agent"]] = bd["by_agent"].get(r["agent"], 0.0) + r["cost"]
        bd["by_agent_tokens"][r["agent"]] = bd["by_agent_tokens"].get(r["agent"], 0) + r["tokens"]["total"]
        b = r["branch"] or "(unknown)"
        bb = by_branch.setdefault(b, {"branch": b, "cost": 0.0, "sessions": 0})
        bb["cost"] += r["cost"]; bb["sessions"] += 1
    for coll in (by_agent, by_model, by_day, by_branch):
        for v in coll.values(): v["cost"] = round(v["cost"], 4)
    for v in by_day.values():  # 当天各 agent 的 cost，按 cost 降序
        v["by_agent"] = {k: round(c, 4) for k, c in sorted(v["by_agent"].items(), key=lambda kv: -kv[1])}
        v["by_agent_tokens"] = {k: v["by_agent_tokens"][k] for k in v["by_agent"]}
    if all(r["branch"] is None for r, _ in rows_pm):
        by_branch = {}
    p = {"id": pid, "name": name, "remote": remote, "paths": paths, "path_missing": path_missing}
    p.update(agg)
    p["by_agent"] = sorted(by_agent.values(), key=lambda x: -x["cost"])
    p["by_model"] = sorted(by_model.values(), key=lambda x: -x["cost"])
    p["by_day"] = sorted(by_day.values(), key=lambda x: x["day"])
    p["by_branch"] = sorted(by_branch.values(), key=lambda x: -x["cost"])
    p["sessions_detail"] = sorted([r for r, _ in rows_pm], key=lambda r: r["started"], reverse=True)
    return p

NOW = datetime(2026, 10, 23, 2, 0, tzinfo=timezone.utc)
def rand_time(days_back_max, days_back_min=0):
    d = rnd.uniform(days_back_min, days_back_max)
    t = NOW - timedelta(days=d)
    # bias to working hours local
    return t.replace(second=0, microsecond=0)

H = "/Users/alice/Documents/GitHub/"
SPECS = [
    # id, name, remote, paths, missing, agents weights, n sessions, scale, days window, branches
    ("github.com/alice/pocket-timer", "PocketTimer", "github.com/alice/pocket-timer",
     [H+"PocketTimer", H+"PocketTimer-fixes-146", H+"PocketTimer-widgets"], False,
     {"claude": 6, "codex": 2, "antigravity": 1}, 34, 1.3, (0, 75), ["main", "release-1.4.5", "fix/146-quota", "feat/widgets", None]),
    ("github.com/bobchen/meterkit", "meterkit", "github.com/bobchen/meterkit", [H+"meterkit"], False,
     {"claude": 3, "antigravity": 2}, 18, 1.0, (2, 60), ["main", "feat/pricing-json", "fix/dedupe-stream"]),
    ("github.com/alice/habit-garden", "HabitGarden", "github.com/alice/habit-garden",
     [H+"HabitGarden", H+"HabitGarden/.worktrees/agy-onboarding"], False,
     {"claude": 2, "antigravity": 3, "codex": 2}, 22, 0.9, (0, 45), ["main", "agy/onboarding", "agy/streaks", None]),
    ("github.com/alice/weather-cli", "weather-cli", "github.com/alice/weather-cli", [H+"weather-cli"], False,
     {"claude": 1}, 7, 0.8, (0, 3), ["main"]),
    ("/Users/alice/Documents/experiments/rust-playground", "rust-playground", None,
     ["/Users/alice/Documents/experiments/rust-playground"], False,
     {"codex": 1}, 6, 0.6, (5, 40), ["master", None]),
    ("gitlab.com/acme/infra-scripts", "infra-scripts", "gitlab.com/acme/infra-scripts", [H+"infra-scripts"], False,
     {"codex": 2, "claude": 1}, 9, 0.5, (10, 80), ["main", "chore/terraform-1.9"]),
    ("github.com/alice/old-blog", "old-blog", "github.com/alice/old-blog", ["/Users/alice/Sites/old-blog"], True,
     {"claude": 1}, 4, 0.4, (70, 90), [None]),
    ("github.com/alice/dotfiles", "dotfiles", "github.com/alice/dotfiles", ["/Users/alice/.dotfiles"], False,
     {"claude": 1}, 1, 0.0003, (20, 21), ["main"]),
]

def pick(weights):
    ks = list(weights); return rnd.choices(ks, [weights[k] for k in ks])[0]

project_rows = {s[0]: [] for s in SPECS}
for pid, name, remote, paths, missing, aw, n, scale, (lo, hi), branches in SPECS:
    for i in range(n):
        agent = pick(aw)
        start = rand_time(hi, lo)
        branch = rnd.choice(branches)
        if agent == "antigravity" and rnd.random() < 0.5: branch = None
        raw = make_raw_session(agent, start, rnd.choice(paths), branch, scale)
        attribution = "dominant"
        if rnd.random() < 0.12: attribution = "cwd"
        if agent == "claude" and rnd.random() < 0.08: attribution = "scratchpad"
        project_rows[pid].append(portion(raw, 1.0, attribution))

# estimated models: inject a few sessions
for pid, agent, model in [("github.com/alice/pocket-timer", "claude", "claude-opus-5-6-preview"),
                          ("github.com/alice/habit-garden", "antigravity", "gemini-3.5-pro-exp"),
                          ("github.com/bobchen/meterkit", "antigravity", "gemini-3.5-pro-exp")]:
    raw = make_raw_session(agent, rand_time(10), H + pid.split("/")[-1], "main", 1.0, models=[model])
    project_rows[pid].append(portion(raw, 1.0, "dominant"))

# override session
raw = make_raw_session("claude", rand_time(30), "/Users/alice/Documents/experiments/meterkit-bench", None, 0.7)
project_rows["github.com/bobchen/meterkit"].append(portion(raw, 1.0, "override"))

# split sessions (same session id across projects)
for a, b, share_a, agent in [("github.com/alice/pocket-timer", "github.com/alice/habit-garden", 0.6, "claude"),
                             ("github.com/bobchen/meterkit", "github.com/alice/weather-cli", 0.55, "claude"),
                             ("github.com/alice/pocket-timer", "gitlab.com/acme/infra-scripts", 0.7, "codex")]:
    raw = make_raw_session(agent, rand_time(20), "/Users/alice", "main", 1.2)
    project_rows[a].append(portion(raw, share_a, "split"))
    project_rows[b].append(portion(raw, round(1 - share_a, 4), "split"))

projects = [build_project(pid, name, remote, paths, missing, project_rows[pid])
            for pid, name, remote, paths, missing, *_ in SPECS]
projects.sort(key=lambda p: -p["cost"])

def bucket(rows_pm):
    agg = aggregate(rows_pm)
    agg["sessions_detail"] = sorted([r for r, _ in rows_pm], key=lambda r: r["started"], reverse=True)
    return agg

un = []
for i in range(5):
    agent = pick({"claude": 2, "antigravity": 1, "codex": 1})
    raw = make_raw_session(agent, rand_time(60), rnd.choice(["/Users/alice", "/Users/alice/Downloads", "/tmp"]), None, 0.3)
    raw["title"] = rnd.choice(["what's the difference between tokio and async-std?", "summarize this pdf", None, "convert this curl to python"])
    un.append(portion(raw, 1.0, "none"))
ex = []
for i in range(3):
    raw = make_raw_session("claude", rand_time(40), "/Users/alice/scratch/llm-evals", None, 0.5)
    ex.append(portion(raw, 1.0, "excluded"))

buckets = {"unattributed": bucket(un), "excluded": bucket(ex),
           "parse_failed": {"sessions": 2, "files": [
               "/Users/alice/.codex/sessions/2026/09/14/rollout-2026-09-14T08-12-55-legacy.jsonl",
               "/Users/alice/.claude/projects/-Users-alice-Documents-GitHub-PocketTimer/0c1d-broken.jsonl"]}}

tt = zero_t()
for p in projects: add_t(tt, p["tokens"])
add_t(tt, buckets["unattributed"]["tokens"]); add_t(tt, buckets["excluded"]["tokens"])
all_days = [d for p in projects for d in (p["first_active"], p["last_active"])] + \
    [buckets[k][f] for k in ("unattributed", "excluded") for f in ("first_active", "last_active")]
totals = {"cost": round(sum(p["cost"] for p in projects) + buckets["unattributed"]["cost"] + buckets["excluded"]["cost"], 4),
          "tokens": tt,
          "sessions": sum(p["sessions"] for p in projects) + buckets["unattributed"]["sessions"] + buckets["excluded"]["sessions"],
          "first_active": min(all_days), "last_active": max(all_days)}

# 额度窗口：claude / codex 有（来源不同），antigravity 没有 → UI 的「Since reset」下 antigravity 不计入。
quota_windows = {
    "claude": {"weekly_resets_at": "2026-10-27T10:00:00Z", "weekly_window_hours": 168,
               "five_hour_resets_at": "2026-10-23T04:30:00Z", "source": "tokei"},
    "codex": {"weekly_resets_at": "2026-10-28T08:00:00Z", "weekly_window_hours": 168,
              "five_hour_resets_at": None, "source": "manual"},
}

def cycle_bounds(anchor_day, now=NOW):
    """Current [cycle_start, cycle_end) for anchor_day at 00:00 LOCAL, as UTC ISO strings.

    The day containing `now` in LOCAL belongs to the cycle that opened on anchor_day
    (this month if today's day-of-month >= anchor, otherwise last month).
    """
    local = now.astimezone(LOCAL)
    year, month = local.year, local.month
    if local.day < anchor_day:
        month -= 1
        if month == 0:
            year, month = year - 1, 12

    def add_month(y, m):
        m += 1
        if m == 13:
            return y + 1, 1
        return y, m

    def iso(y, m, d):
        dt = datetime(y, m, d, 0, 0, tzinfo=LOCAL).astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    end_y, end_m = add_month(year, month)
    return iso(year, month, anchor_day), iso(end_y, end_m, anchor_day)

# 订阅：claude / codex 有，antigravity 没有 → UI 的「Billing cycle」下 antigravity 不计入。
# 账期按 anchor_day 在 Asia/Shanghai 的 00:00 折算（报告 generated_at 落在 10 月 23 日）。
claude_start, claude_end = cycle_bounds(25)
codex_start, codex_end = cycle_bounds(1)
subscriptions = {
    "claude": {
        "plan": "max_5x", "plan_label": "Claude Max 5x", "monthly_price_usd": 100.0,
        "cycle_start": claude_start, "cycle_end": claude_end, "anchor_day": 25,
        "cycle_source": "subscription_date", "extra_usage_enabled": False, "source": "detected",
    },
    "codex": {
        "plan": "plus", "plan_label": "ChatGPT Plus", "monthly_price_usd": 20.0,
        "cycle_start": codex_start, "cycle_end": codex_end, "anchor_day": 1,
        "cycle_source": "calendar_month", "extra_usage_enabled": False, "source": "detected",
    },
}
out = {"schema_version": 1, "generated_at": "2026-10-23T02:00:00Z", "generated_by": "generate_sample.py",
       "timezone": "Asia/Shanghai", "currency": "USD",
       "cost_note": "API-equivalent cost estimated from public API prices. Not actual subscription spend.",
       "config": {"dominant_threshold": 0.8}, "quota_windows": quota_windows,
       "subscriptions": subscriptions,
       "totals": totals, "projects": projects, "buckets": buckets}
import os
dest = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample.json")
json.dump(out, open(dest, "w"), indent=2, ensure_ascii=False)

# verify invariants
s = sum(p["cost"] for p in projects) + buckets["unattributed"]["cost"] + buckets["excluded"]["cost"]
assert abs(totals["cost"] - s) < 0.01
for p in projects:
    for key in ("by_agent", "by_model", "by_day"):
        assert abs(sum(x["cost"] for x in p[key]) - p["cost"]) < 0.01, (p["id"], key)
    assert abs(sum(x["cost"] for x in p["sessions_detail"]) - p["cost"]) < 0.01
    assert sum(x["tokens"]["total"] for x in p["by_model"]) == p["tokens"]["total"]
    assert sum(x["tokens"] for x in p["by_day"]) == p["tokens"]["total"]
    for d in p["by_day"]:
        assert abs(sum(d["by_agent"].values()) - d["cost"]) < 0.01, (p["id"], d["day"])
        assert set(d["by_agent"]) <= {a["agent"] for a in p["by_agent"]}, (p["id"], d["day"])
        assert set(d["by_agent_tokens"]) == set(d["by_agent"]), (p["id"], d["day"])
        assert sum(d["by_agent_tokens"].values()) == d["tokens"], (p["id"], d["day"])
assert set(subscriptions) == {"claude", "codex"}
assert subscriptions["claude"]["plan"] == "max_5x"
assert subscriptions["claude"]["monthly_price_usd"] == 100.0
assert subscriptions["claude"]["anchor_day"] == 25
assert subscriptions["claude"]["cycle_source"] == "subscription_date"
assert subscriptions["claude"]["extra_usage_enabled"] is False
assert subscriptions["claude"]["source"] == "detected"
assert subscriptions["claude"]["cycle_start"] == "2026-09-24T16:00:00Z"
assert subscriptions["claude"]["cycle_end"] == "2026-10-24T16:00:00Z"
assert subscriptions["codex"]["plan"] == "plus"
assert subscriptions["codex"]["monthly_price_usd"] == 20.0
assert subscriptions["codex"]["anchor_day"] == 1
assert subscriptions["codex"]["cycle_source"] == "calendar_month"
assert subscriptions["codex"]["source"] == "detected"
assert subscriptions["codex"]["cycle_start"] == "2026-09-30T16:00:00Z"
assert subscriptions["codex"]["cycle_end"] == "2026-10-31T16:00:00Z"
print("ok", round(totals["cost"], 2), totals["sessions"])
for p in projects: print(f'{p["name"]:16} {p["cost"]:10.4f} {p["sessions"]:3} {[a["agent"] for a in p["by_agent"]]} branches={len(p["by_branch"])}')
print("buckets", buckets["unattributed"]["cost"], buckets["excluded"]["cost"])
