"""Generate ui/fixtures/disk-sample.json following CONTRACT.md §10.

Usage: python3 fixtures/generate_disk_sample.py [out.json]   (default: fixtures/disk-sample.json)

Five agents, paths under /Users/alice. Totals format as 55.2 GB / 31.4 GB,
Codex as 11.8 GB (decimal, 1000-based). One entry per deletable class, one
blocked entry per reason. Reclaimable is every entry that is not `never`
and has an empty blocked list.
"""
import json
import sys

TOTAL = 55_200_000_000
RECLAIMABLE = 31_400_000_000

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
    ("gemini", "Gemini CLI", [
        ("gemini:sessions", "sessions", "/Users/alice/.gemini/sessions",
         4_200_000_000, 510, "2026-04-04", "2026-10-23", "after_import", [],
         "Gemini session logs already copied into the ledger."),
        ("gemini:scratch", "scratch", "/Users/alice/.gemini/tmp",
         2_200_000_000, 88, "2026-10-20", "2026-10-25", "when_clean", ["active"],
         "Temporary files still in use."),
        ("gemini:memory", "memory", "/Users/alice/.gemini/memory",
         4_200_000_000, 15, "2026-02-02", "2026-09-30", "never", [],
         "Gemini memory store. Never deleted."),
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
    ("cursor", "Cursor", [
        ("cursor:cache", "cache", "/Users/alice/Library/Application Support/Cursor/Cache",
         626_000_000, 4100, "2026-09-12", "2026-10-18", "always", [],
         "Editor cache. Cursor recreates it."),
        ("cursor:sessions", "sessions", "/Users/alice/Library/Application Support/Cursor/User/globalStorage",
         4_374_000_000, 220, "2026-03-15", "2026-10-24", "after_import", [],
         "Chat transcripts already imported into the ledger."),
        ("cursor:other", "other", "/Users/alice/Library/Application Support/Cursor/User/workspaceStorage",
         3_000_000_000, 96, "2026-02-11", "2026-10-16", "never", [],
         "Workspace state the editor still needs."),
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
    assert len(agents) == 5
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
