"""Generate ui/fixtures/disk-sample.json following CONTRACT.md §10.

Usage: python3 fixtures/generate_disk_sample.py [out.json]   (default: fixtures/disk-sample.json)

Ten agents, paths under /Users/alice. Totals format as 42.2 GB / 25.9 GB,
Codex as 11.8 GB (decimal, 1000-based). One entry per deletable class, one
blocked entry per reason. Reclaimable is every entry that is not `never`
and has an empty blocked list.
"""
import json
import sys

TOTAL = 42_200_000_000
RECLAIMABLE = 25_900_000_000

AGENTS = [
    ("claude", "Claude Code", [
        ("claude:sessions", "sessions", "/Users/alice/.claude/projects",
         9_200_000_000, 1204, "2026-01-12", "2026-10-25", "after_import", [],
         "Project session logs. Numbers stay in the ledger after deletion."),
        ("claude:cache", "cache", "/Users/alice/Library/Caches/claude-cli",
         2_400_000_000, 860, "2026-08-02", "2026-10-24", "always", [],
         "CLI download cache. Claude recreates it."),
        ("claude:memory", "memory", "/Users/alice/.claude/memory",
         3_200_000_000, 42, "2026-03-01", "2026-10-20", "never", [],
         "Cross-session memory. Never deleted."),
        ("claude:scratch", "scratch", "/Users/alice/.claude/scratch",
         1_600_000_000, 17, "2026-10-18", "2026-10-25", "when_clean", ["active"],
         "Scratch files touched in the last day."),
    ]),
    ("codex", "Codex CLI", [
        ("codex:sessions", "sessions", "/Users/alice/.codex/sessions",
         4_600_000_000, 248, "2026-06-30", "2026-10-25", "after_import", ["not_imported"],
         "Session logs. Numbers are kept in the ledger after deletion."),
        ("codex:cache", "cache", "/Users/alice/Library/Caches/codex",
         1_100_000_000, 3412, "2026-07-14", "2026-10-22", "always", [],
         "Package cache. Safe to remove; Codex recreates it."),
        ("codex:worktrees", "worktrees", "/Users/alice/.codex/worktrees",
         6_100_000_000, 6, "2026-09-01", "2026-10-11", "when_clean", [],
         "Git worktrees with a clean tree. Removed with git worktree remove."),
    ]),
    ("antigravity", "Antigravity CLI", [
        ("antigravity:sessions", "sessions", "/Users/alice/.gemini/antigravity-cli/conversations",
         2_600_000_000, 73, "2026-05-19", "2026-10-21", "after_import", [],
         "Conversation databases already imported."),
        ("antigravity:worktrees", "worktrees", "/Users/alice/.gemini/antigravity-cli/worktrees",
         3_400_000_000, 4, "2026-08-08", "2026-10-19", "when_clean", ["uncommitted_changes"],
         "Worktrees with uncommitted changes. Left in place."),
        ("antigravity:cache", "cache", "/Users/alice/Library/Caches/antigravity-cli",
         800_000_000, 640, "2026-06-01", "2026-10-12", "always", [],
         "Antigravity cache. Safe to remove."),
        ("antigravity:memory", "memory", "/Users/alice/.gemini/antigravity-cli/brain",
         1_600_000_000, 9, "2026-01-20", "2026-10-01", "never", [],
         "Cross-session memory. Never deleted."),
    ]),
    ("grok", "Grok CLI", [
        ("grok:sessions", "sessions", "/Users/alice/.grok/sessions",
         1_200_000_000, 84, "2026-08-10", "2026-10-24", "after_import", [],
         "Grok sessions. Numbers stay in the ledger after deletion."),
        ("grok:bundled", "other", "/Users/alice/.grok/bundled",
         800_000_000, 12, "2026-08-01", "2026-09-15", "never", [],
         "Bundled models and assets. Never deleted."),
    ]),
    ("qwen", "Qwen Code", [
        ("qwen:sessions", "sessions", "/Users/alice/.qwen/usage",
         600_000_000, 45, "2026-07-01", "2026-10-23", "after_import", [],
         "Qwen Code monthly usage logs."),
        ("qwen:projects", "other", "/Users/alice/.qwen/projects",
         400_000_000, 18, "2026-07-01", "2026-10-20", "never", [],
         "Qwen project metadata. Kept across sessions."),
    ]),
    ("commandcode", "Command Code", [
        ("commandcode:sessions", "sessions", "/Users/alice/.commandcode/projects",
         500_000_000, 32, "2026-08-15", "2026-10-22", "after_import", [],
         "Command Code project sessions."),
    ]),
    ("minimax", "MiniMax", [
        ("minimax:sessions", "sessions", "/Users/alice/.minimax",
         300_000_000, 3, "2026-09-01", "2026-10-24", "never", [],
         "MiniMax SQLite database. DB-backed sessions are never deleted by disk clean."),
    ]),
    ("opencode", "OpenCode", [
        ("opencode:sessions", "sessions", "/Users/alice/.local/share/opencode",
         400_000_000, 4, "2026-08-20", "2026-10-24", "never", [],
         "OpenCode SQLite database. DB-backed sessions are never deleted by disk clean."),
    ]),
    ("copilot", "Copilot CLI", [
        ("copilot:sessions", "sessions", "/Users/alice/.copilot/session-state",
         700_000_000, 150, "2026-06-10", "2026-10-23", "after_import", [],
         "Copilot CLI session state."),
    ]),
    ("claude-desktop", "Claude Desktop", [
        ("claude-desktop:cache", "cache", "/Users/alice/Library/Application Support/Claude/Cache",
         500_000_000, 3200, "2026-09-10", "2026-10-25", "always", [],
         "Claude desktop app cache. Safe to delete."),
        ("claude-desktop:code-cache", "cache", "/Users/alice/Library/Application Support/Claude/Code Cache",
         200_000_000, 1100, "2026-09-10", "2026-10-25", "always", [],
         "Claude desktop code cache. Safe to delete."),
    ]),
]


def entry(spec):
    eid, kind, path, nbytes, files, oldest, newest, deletable, blocked, note = spec
    return {
        "id": eid, "kind": kind, "path": path, "bytes": nbytes, "files": files,
        "oldest": oldest, "newest": newest, "deletable": deletable,
        "blocked": blocked, "note": note,
    }


def main():
    agents = []
    for key, label, specs in AGENTS:
        entries = [entry(s) for s in specs]
        agents.append({
            "agent": key, "label": label,
            "bytes": sum(e["bytes"] for e in entries),
            "entries": entries,
        })
    doc = {
        "schema_version": 1,
        "generated_at": "2026-10-25T10:00:00Z",
        "total_bytes": sum(a["bytes"] for a in agents),
        "reclaimable_bytes": sum(
            e["bytes"] for a in agents for e in a["entries"]
            if e["deletable"] != "never" and not e["blocked"]
        ),
        "agents": agents,
    }
    assert doc["total_bytes"] == TOTAL, doc["total_bytes"]
    assert doc["reclaimable_bytes"] == RECLAIMABLE, doc["reclaimable_bytes"]
    assert len(agents) == 10
    assert next(a["bytes"] for a in agents if a["agent"] == "codex") == 11_800_000_000
    deletable = {e["deletable"] for a in agents for e in a["entries"]}
    assert deletable >= {"always", "after_import", "when_clean", "never"}
    kinds = {e["kind"] for a in agents for e in a["entries"]}
    assert kinds >= {"sessions", "scratch", "worktrees", "cache", "memory", "other"}
    reasons = {r for a in agents for e in a["entries"] for r in e["blocked"]}
    assert reasons >= {"not_imported", "uncommitted_changes", "active"}
    for a in agents:
        assert a["bytes"] == sum(e["bytes"] for e in a["entries"]), a["agent"]
        for e in a["entries"]:
            assert e["path"].startswith("/Users/alice/"), e["path"]
    out = sys.argv[1] if len(sys.argv) > 1 else "fixtures/disk-sample.json"
    with open(out, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    print("wrote %s (%d agents, %d bytes)" % (out, len(agents), doc["total_bytes"]))


if __name__ == "__main__":
    main()
