"""Disk usage of local AI tools, and a Trash-only clean.

``kanjo disk`` reports bytes with ``st_blocks * 512`` (actual allocated space).
``kanjo disk clean`` moves files into ``~/.Trash/kanjo-<timestamp>/`` and never
unlinks them. Git worktrees are removed with ``git worktree remove`` instead.
Nothing is moved unless ``--yes`` is passed. The UI only calls this command.
"""

from __future__ import annotations

import errno
import os
import re
import shutil
import stat
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from . import disk_cache
from .ledger import Ledger, paths_of
from .sources import antigravity, claude, codex, copilot, minimax, opencode
from .sources.base import AGENT_LABELS, env_dirs, iso_utc, local_day

ACTIVE_SECONDS = 24 * 60 * 60
DELETABLE = {
    "cache": "always",
    "sessions": "after_import",
    "scratch": "when_clean",
    "worktrees": "when_clean",
    "memory": "never",
    "other": "never",
}
NOTES = {
    "sessions": "Session logs. Numbers are kept in the ledger after deletion.",
    "scratch": "Scratch space. Cleaned only when nothing changed in the last 24 hours.",
    "worktrees": "Git worktrees. Removed with git worktree remove when clean and idle.",
    "cache": "Cache. Safe to delete.",
    "memory": "Memory kept across sessions. Never deleted.",
    "other": "Not deleted.",
}
LABELS = dict(AGENT_LABELS)
LABELS["claude-desktop"] = "Claude Desktop"
AGENT_ORDER = ["claude", "codex", "antigravity", "grok", "qwen", "commandcode", "minimax", "opencode", "copilot", "claude-desktop"]
_PARSERS = {
    "claude": claude,
    "codex": codex,
    "antigravity": antigravity,
    "minimax": minimax,
    "opencode": opencode,
    "copilot": copilot,
}
_OLDER = re.compile(r"^(\d+)d$")


def parse_older_than(text: str) -> int:
    match = _OLDER.match(text or "")
    if not match:
        raise ValueError("expected Nd, for example 30d")
    return int(match.group(1))


def trash_base() -> str:
    explicit = os.environ.get("KANJO_TRASH_DIR")
    if explicit:
        return os.path.expanduser(explicit)
    return os.path.expanduser("~/.Trash")


def default_roots() -> dict:
    """Directories ``kanjo disk`` scans. Parser overrides relocate the whole tool root.

    ``KANJO_CLAUDE_DIR`` / ``KANJO_CODEX_DIR`` / ``KANJO_ANTIGRAVITY_DIR`` replace the
    log directories the parsers use. Shell snapshots, debug logs, Codex worktrees
    and logs, and the Antigravity brain and cache are siblings of those directories
    (so the default layout is unchanged). ``KANJO_SCRATCH_DIR``, ``KANJO_GROK_DIR``
    and ``KANJO_CLAUDE_APP_CACHE`` exist so tests never touch the real machine.
    """
    return {
        "claude_projects": env_dirs("KANJO_CLAUDE_DIR", ["~/.claude/projects"]),
        "scratch": os.path.expanduser(os.environ.get("KANJO_SCRATCH_DIR") or ("/tmp/claude-%d" % os.getuid())),
        "codex_dirs": env_dirs("KANJO_CODEX_DIR", ["~/.codex/sessions", "~/.codex/archived_sessions"]),
        "antigravity_dirs": env_dirs("KANJO_ANTIGRAVITY_DIR", ["~/.gemini/antigravity-cli/conversations"]),
        "grok": os.path.expanduser(os.environ.get("KANJO_GROK_DIR") or "~/.grok"),
        "qwen": os.path.expanduser(os.environ["KANJO_QWEN_DIR"]) if os.environ.get("KANJO_QWEN_DIR") else (None if os.environ.get("KANJO_DATA_DIR") else os.path.expanduser("~/.qwen")),
        "commandcode": os.path.expanduser(os.environ["KANJO_COMMANDCODE_DIR"]) if os.environ.get("KANJO_COMMANDCODE_DIR") else (None if os.environ.get("KANJO_DATA_DIR") else os.path.expanduser("~/.commandcode")),
        "claude_app": os.path.expanduser(
            os.environ.get("KANJO_CLAUDE_APP_CACHE") or "~/Library/Application Support/Claude"),
        "minimax": os.path.expanduser(os.environ.get("KANJO_MINIMAX_DIR") or "~/.minimax"),
        "opencode": os.path.expanduser(os.environ.get("KANJO_OPENCODE_DIR") or "~/.local/share/opencode"),
        "copilot": os.path.expanduser(os.environ.get("KANJO_COPILOT_DIR") or "~/.copilot"),
    }


def measure(path: str, now: float, exclude: Optional[List[str]] = None,
            _root_stat=None, _submit=None) -> dict:
    """Allocated bytes (``st_blocks * 512``) and file count under ``path``.

    Directories count toward bytes, not ``files``. Symlinks are not followed.
    Permission errors are skipped and counted in ``errors``. ``active`` is true
    when any file or directory inside was modified in the last 24 hours.
    Internally, ``_submit`` delegates first-level directories to the report pool;
    ``_root_stat`` reuses their stat result so each directory is counted once.
    """
    excluded = set(_norm(p) for p in (exclude or []))
    total = 0
    files = 0
    errors = 0
    oldest = None
    newest = None

    def note(st, is_file: bool) -> None:
        nonlocal total, files, oldest, newest
        total += int(st.st_blocks) * 512
        if is_file:
            files += 1
        ts = st.st_mtime
        if oldest is None or ts < oldest:
            oldest = ts
        if newest is None or ts > newest:
            newest = ts

    try:
        note(os.lstat(path) if _root_stat is None else _root_stat, False)
    except OSError:
        errors += 1
        return {"bytes": 0, "files": 0, "oldest": None, "newest": None, "errors": errors, "active": False}

    stack = [path]
    seen = set()
    while stack:
        current = stack.pop()
        current_norm = _norm(current)
        if current_norm in seen:
            continue
        seen.add(current_norm)
        try:
            iterator = os.scandir(current)
        except OSError:
            errors += 1
            continue
        with iterator:
            for ent in iterator:
                if excluded and _norm(ent.path) in excluded:
                    continue
                try:
                    st = ent.stat(follow_symlinks=False)
                except OSError:
                    errors += 1
                    continue
                # lstat already tells us the type, including symlinks. Reuse it.
                if stat.S_ISDIR(st.st_mode):
                    if _submit is not None:
                        _submit(ent.path, st)
                    else:
                        note(st, False)
                        stack.append(ent.path)
                    continue
                note(st, True)
    active = newest is not None and (now - newest) < ACTIVE_SECONDS
    return {"bytes": total, "files": files, "oldest": oldest, "newest": newest, "errors": errors, "active": active}


def report(roots: Optional[dict] = None, now: Optional[float] = None, ledger: Optional[Ledger] = None,
           max_age: float = 600, rescan: bool = False) -> dict:
    """CONTRACT.md section 10 document. Reads the ledger; caches the report."""
    started = time.monotonic()
    now = time.time() if now is None else now
    roots = default_roots() if roots is None else roots
    if not rescan:
        cached = disk_cache.load(roots, now, max_age)
        if cached is not None:
            return cached
    ledger = ledger or Ledger()
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as executor:
        grouped = _collect(roots, now, _imported_index(ledger), executor)
    agents = []
    total = 0
    reclaim = 0
    seen = set()
    for agent in AGENT_ORDER + [a for a in grouped if a not in AGENT_ORDER]:
        if agent in seen:
            continue
        seen.add(agent)
        entries = grouped.get(agent) or []
        if not entries:
            continue
        abytes = sum(e["bytes"] for e in entries)
        total += abytes
        for entry in entries:
            if entry["deletable"] != "never" and not entry["blocked"]:
                reclaim += entry["bytes"]
        agents.append({
            "agent": agent,
            "label": LABELS.get(agent, agent),
            "bytes": abytes,
            "entries": entries,
        })
    doc = {
        "schema_version": 1,
        "generated_at": iso_utc(now),
        "total_bytes": total,
        "reclaimable_bytes": reclaim,
        "agents": agents,
        "scan_seconds": time.monotonic() - started,
        "cached": False,
        "scanned_at": datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    disk_cache.save(doc, roots)
    return doc


def clean(ids: List[str], older_than_days: Optional[int] = None, dry_run: bool = False, yes: bool = False,
          now: Optional[float] = None, roots: Optional[dict] = None, trash_dir: Optional[str] = None,
          ledger: Optional[Ledger] = None) -> dict:
    """Move ``ids`` into the Trash. Without ``yes``, or with ``dry_run``, nothing is moved.

    ``older_than_days`` keeps files newer than that many days. Worktrees are removed
    as a whole (only when every file is old enough) via ``git worktree remove``.
    On a sessions entry, a log file with no ledger row is skipped even when the
    entry itself is allowed; ``--older-than`` still moves the other files when
    ``not_imported`` is the only block.
    """
    now = time.time() if now is None else now
    ledger = ledger or Ledger()
    doc = report(roots=roots, now=now, ledger=ledger, rescan=True)
    imported = _imported_index(ledger)
    by_id = {}
    owners = {}
    for agent in doc["agents"]:
        for entry in agent["entries"]:
            by_id[entry["id"]] = entry
            owners[entry["id"]] = agent["agent"]
    do_it = bool(yes) and not dry_run
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    trash_root = os.path.join(trash_dir or trash_base(), "kanjo-" + stamp)
    moved: List[str] = []
    skipped = []
    freed = 0
    for eid in ids:
        entry = by_id.get(eid)
        if entry is None:
            skipped.append({"id": eid, "reason": "not_found"})
            continue
        if _refused(entry["path"]):
            skipped.append({"id": eid, "reason": "refused"})
            continue
        if entry["deletable"] == "never":
            skipped.append({"id": eid, "reason": "never"})
            continue
        agent = owners.get(eid, "")
        partial = _partial_session_clean(entry, agent, older_than_days)
        if entry["blocked"] and not partial:
            skipped.append({"id": eid, "reason": ",".join(entry["blocked"])})
            continue
        try:
            if entry["kind"] == "worktrees":
                part_moved, part_freed, reason = _clean_worktree(entry, older_than_days, now, do_it)
                file_skips: List[dict] = []
            else:
                part_moved, part_freed, reason, file_skips = _clean_tree(
                    entry, older_than_days, now, do_it, trash_root, agent=agent, imported=imported)
        except OSError:
            # A partial per-file clean may already have moved files before failing.
            if do_it:
                disk_cache.invalidate()
            skipped.append({"id": eid, "reason": "move_failed"})
            continue
        if reason:
            skipped.append({"id": eid, "reason": reason})
            skipped.extend(file_skips)
            continue
        moved.extend(part_moved)
        freed += part_freed
        skipped.extend(file_skips)
    if do_it and moved:
        disk_cache.invalidate()
    return {"moved": moved, "freed_bytes": freed, "skipped": skipped}


# ---- scanning targets -----------------------------------------------------------------
def _collect(roots: dict, now: float, imported: Dict[str, set],
             executor: ThreadPoolExecutor) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    used = set()
    pending = []

    def take_id(eid: str) -> str:
        if eid not in used:
            return eid
        n = 2
        while "%s:%d" % (eid, n) in used:
            n += 1
        return "%s:%d" % (eid, n)

    def add(agent: str, eid: str, kind: str, path: str, blocked=None, note=None, exclude=None, deletable=None) -> None:
        used.add(eid)
        counts = executor.submit(_import_counts, agent, path, imported) if kind == "sessions" else None
        dirty = executor.submit(_worktree_dirty, path) if kind == "worktrees" else None
        parts = []
        shallow = None
        if eid == "claude:scratch":
            # Submit each first-level directory into the SAME pool as other entries.
            # The caller scans root files; workers never wait for other workers.
            def submit(child, st):
                parts.append(executor.submit(measure, child, now, _root_stat=st))
            shallow = measure(path, now, _submit=submit)
        else:
            parts.append(executor.submit(measure, path, now, exclude))
        pending.append((agent, eid, kind, path, blocked or [], note, counts, dirty, shallow, parts, deletable))

    projects = list(roots.get("claude_projects") or [])
    for path in projects:
        if _isdir(path):
            add("claude", _session_id("claude", path, used), "sessions", path)
    for parent in _parents(projects):
        for name, eid in (("shell-snapshots", "claude:shell-snapshots"), ("debug", "claude:debug")):
            path = os.path.join(parent, name)
            if _isdir(path):
                add("claude", take_id(eid), "cache", path)
    scratch = roots.get("scratch")
    if scratch and _isdir(scratch):
        add("claude", "claude:scratch", "scratch", scratch)

    codex_dirs = list(roots.get("codex_dirs") or [])
    for path in codex_dirs:
        if _isdir(path):
            add("codex", _session_id("codex", path, used), "sessions", path)
    for parent in _parents(codex_dirs):
        wt_root = os.path.join(parent, "worktrees")
        if _isdir(wt_root):
            for rel, wpath in _find_worktrees(wt_root):
                add("codex", take_id("codex:worktree:" + rel), "worktrees", wpath)
        logs = os.path.join(parent, "logs")
        if _isdir(logs):
            add("codex", take_id("codex:logs"), "cache", logs)

    agy_dirs = list(roots.get("antigravity_dirs") or [])
    for path in agy_dirs:
        if _isdir(path):
            add("antigravity", _session_id("antigravity", path, used), "sessions", path)
    for parent in _parents(agy_dirs):
        brain = os.path.join(parent, "brain")
        if _isdir(brain):
            scratches = _brain_scratches(brain)
            for brain_id, spath in scratches:
                add("antigravity", take_id("antigravity:scratch:" + brain_id), "scratch", spath)
            add("antigravity", take_id("antigravity:memory"), "memory", brain,
                exclude=[p for _bid, p in scratches])
        cache = os.path.join(parent, "cache")
        if _isdir(cache):
            add("antigravity", take_id("antigravity:cache"), "cache", cache)

    grok = roots.get("grok")
    if grok:
        sessions = os.path.join(grok, "sessions")
        if _isdir(sessions):
            add("grok", take_id("grok:sessions"), "sessions", sessions, ["not_imported"],
                note="Grok sessions.")
        bundled = os.path.join(grok, "bundled")
        if _isdir(bundled):
            add("grok", take_id("grok:bundled"), "other", bundled)

    qwen = roots.get("qwen")
    if qwen:
        usage = os.path.join(qwen, "usage")
        if _isdir(usage):
            add("qwen", take_id("qwen:sessions"), "sessions", usage, ["not_imported"],
                note="Qwen Code monthly usage logs.")
        projects = os.path.join(qwen, "projects")
        if _isdir(projects):
            add("qwen", take_id("qwen:projects"), "other", projects)

    cmd = roots.get("commandcode")
    if cmd:
        projects = os.path.join(cmd, "projects")
        if _isdir(projects):
            add("commandcode", take_id("commandcode:sessions"), "sessions", projects, ["not_imported"],
                note="Command Code project sessions.")

    app = roots.get("claude_app")
    if app:
        for name, eid, note in (
            ("Cache", "claude-desktop:cache", "Claude desktop app cache. Safe to delete."),
            ("Code Cache", "claude-desktop:code-cache", "Claude desktop code cache. Safe to delete."),
            ("GPUCache", "claude-desktop:gpucache", "Claude desktop GPU cache. Safe to delete."),
        ):
            path = os.path.join(app, name)
            if _isdir(path):
                add("claude-desktop", take_id(eid), "cache", path, note=note)

    minimax_root = roots.get("minimax")
    if minimax_root and (_isdir(minimax_root) or os.path.isfile(minimax_root)):
        db = os.path.join(minimax_root, "sqlite.db") if _isdir(minimax_root) else minimax_root
        if os.path.isfile(db):
            add("minimax", take_id("minimax:sessions"), "sessions", minimax_root,
                note="MiniMax SQLite database. DB-backed sessions are never deleted by disk clean.",
                deletable="never")

    opencode_root = roots.get("opencode")
    if opencode_root and (_isdir(opencode_root) or os.path.isfile(opencode_root)):
        db = os.path.join(opencode_root, "opencode.db") if _isdir(opencode_root) else opencode_root
        if os.path.isfile(db):
            add("opencode", take_id("opencode:sessions"), "sessions", opencode_root,
                note="OpenCode SQLite database. DB-backed sessions are never deleted by disk clean.",
                deletable="never")

    copilot_root = roots.get("copilot")
    if copilot_root and _isdir(copilot_root):
        state_dir = os.path.join(copilot_root, "session-state")
        if _isdir(state_dir):
            add("copilot", take_id("copilot:sessions"), "sessions", state_dir)
        elif os.path.isfile(os.path.join(copilot_root, "session-store.db")):
            add("copilot", take_id("copilot:sessions"), "sessions", copilot_root,
                note="Copilot CLI session database.", deletable="never")

    # Resolve in discovery order so scheduling never changes ids or JSON ordering.
    for agent, eid, kind, path, blocked, note, counts, dirty, shallow, parts, deletable in pending:
        measured = _sum_measurements(([shallow] if shallow is not None else [])
                                     + [part.result() for part in parts], now)
        if dirty is not None and dirty.result():
            blocked.append("uncommitted_changes")
        if kind in ("scratch", "worktrees") and measured["active"]:
            blocked.append("active")
        log_files = imported_files = None
        if counts is not None:
            log_files, imported_files = counts.result()
            if agent == "grok":
                log_files = measured["files"]
            elif imported_files < log_files:
                blocked.append("not_imported")
        entry = _make(eid, kind, path, measured, blocked, note=note,
                      log_files=log_files, imported_files=imported_files, deletable=deletable)
        grouped.setdefault(agent, []).append(entry)
    return grouped


def _sum_measurements(parts: List[dict], now: float) -> dict:
    oldest = [part["oldest"] for part in parts if part["oldest"] is not None]
    newest = [part["newest"] for part in parts if part["newest"] is not None]
    last = max(newest) if newest else None
    return {
        "bytes": sum(part["bytes"] for part in parts),
        "files": sum(part["files"] for part in parts),
        "oldest": min(oldest) if oldest else None,
        "newest": last,
        "errors": sum(part["errors"] for part in parts),
        "active": last is not None and (now - last) < ACTIVE_SECONDS,
    }


def _make(eid: str, kind: str, path: str, measured: dict, blocked: List[str], note: Optional[str] = None,
         log_files: Optional[int] = None, imported_files: Optional[int] = None, deletable: Optional[str] = None) -> dict:
    entry = {
        "id": eid,
        "kind": kind,
        "path": path,
        "bytes": measured["bytes"],
        "files": measured["files"],
        "oldest": local_day(measured["oldest"]) if measured["oldest"] is not None else None,
        "newest": local_day(measured["newest"]) if measured["newest"] is not None else None,
        "deletable": deletable or DELETABLE[kind],
        "blocked": list(blocked),
        "note": note or NOTES[kind],
        "skipped_errors": measured["errors"],
    }
    if log_files is not None:
        entry["log_files"] = log_files
        entry["imported_files"] = 0 if imported_files is None else imported_files
    return entry


def _session_id(agent: str, path: str, used: set) -> str:
    base = os.path.basename(os.path.normpath(path))
    if agent == "codex" and base == "archived_sessions":
        eid = "codex:archived_sessions"
    elif agent == "codex" and base == "sessions":
        eid = "codex:sessions"
    elif agent == "claude" and base == "projects":
        eid = "claude:sessions"
    elif agent == "antigravity" and base == "conversations":
        eid = "antigravity:sessions"
    else:
        eid = "%s:sessions:%s" % (agent, base)
    if eid in used:
        n = 2
        while "%s:%d" % (eid, n) in used:
            n += 1
        eid = "%s:%d" % (eid, n)
    used.add(eid)
    return eid


def _imported_index(ledger: Ledger) -> Dict[str, set]:
    """``agent -> source paths`` that have any ledger row. Signature is ignored.

    A later export re-imports a file whose size or mtime changed. Matching the
    signature here kept live session logs ``not_imported`` forever. Every path
    on a row counts, including the other files of a merged session and the
    lightweight empty / error rows.
    """
    found: Dict[str, set] = {}
    for key, entry in ledger.entries.items():
        if not isinstance(entry, dict):
            continue
        agent = _entry_agent(key, entry)
        if not agent:
            continue
        bucket = found.setdefault(agent, set())
        for path in paths_of(entry):
            bucket.add(path)
            bucket.add(os.path.normpath(path))
    return found


def _entry_agent(key: object, entry: dict) -> Optional[str]:
    session = entry.get("session")
    if isinstance(session, dict):
        agent = session.get("agent")
        if isinstance(agent, str) and agent:
            return agent
    if isinstance(key, str) and "\0" in key:
        return key.split("\0", 1)[0]
    return None


def _import_counts(agent: str, root: str, imported: Dict[str, set]) -> Tuple[int, int]:
    """``(log_files, imported_files)`` from ``discover()`` under ``root``."""
    logs = _log_paths(agent, root)
    if logs is None:
        return 0, 0
    known = imported.get(agent) or set()
    imported_files = sum(1 for path in logs if path in known or os.path.normpath(path) in known)
    return len(logs), imported_files


def _log_paths(agent: str, root: str) -> Optional[List[str]]:
    module = _PARSERS.get(agent)
    if module is None:
        return None
    return [path for path, _parent in module.discover([root])]


def _partial_session_clean(entry: dict, agent: str, days: Optional[int]) -> bool:
    """Per-file clean when ``--older-than`` is set and ``not_imported`` is the only block.

    Grok has no parser, so it stays blocked as a whole: every file would
    otherwise look like a non-log and be moved.
    """
    return (
        days is not None
        and entry.get("kind") == "sessions"
        and entry.get("blocked") == ["not_imported"]
        and agent in _PARSERS
    )


def _find_worktrees(root: str) -> List[Tuple[str, str]]:
    """``(relative id, path)`` for each directory under ``root`` that has a ``.git``."""
    found = []

    def walk(path: str, rel: str) -> None:
        try:
            children = list(os.scandir(path))
        except OSError:
            return
        dirs = [ent for ent in children if ent.is_dir(follow_symlinks=False) and not ent.is_symlink()]
        dirs.sort(key=lambda ent: ent.name)
        for ent in dirs:
            child_rel = ent.name if not rel else "%s/%s" % (rel, ent.name)
            git_path = os.path.join(ent.path, ".git")
            if os.path.lexists(git_path):
                found.append((child_rel, ent.path))
            else:
                walk(ent.path, child_rel)

    if _isdir(root):
        walk(root, "")
    return found


def _brain_scratches(brain_root: str) -> List[Tuple[str, str]]:
    found = []
    try:
        kids = list(os.scandir(brain_root))
    except OSError:
        return found
    for ent in kids:
        if not ent.is_dir(follow_symlinks=False) or ent.is_symlink():
            continue
        scratch = os.path.join(ent.path, "scratch")
        if os.path.isdir(scratch):
            found.append((ent.name, scratch))
    found.sort(key=lambda item: item[0])
    return found


def _worktree_dirty(path: str) -> bool:
    """True when ``git status --porcelain`` is non-empty, or git cannot say."""
    try:
        proc = subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-C", path, "status", "--porcelain"],
            capture_output=True, text=True, timeout=60, env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    if proc.returncode != 0:
        return True
    return bool(proc.stdout.strip())


def _main_repo(path: str) -> Optional[str]:
    """Main repository of a linked worktree, from its ``.git`` file."""
    git_file = os.path.join(path, ".git")
    if os.path.isdir(git_file) or not os.path.isfile(git_file):
        return None
    try:
        with open(git_file, encoding="utf-8") as handle:
            line = handle.read().strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = line.split(":", 1)[1].strip()
    if not os.path.isabs(gitdir):
        gitdir = os.path.normpath(os.path.join(path, gitdir))
    common_file = os.path.join(gitdir, "commondir")
    if os.path.isfile(common_file):
        try:
            with open(common_file, encoding="utf-8") as handle:
                common = handle.read().strip()
        except OSError:
            common = ""
        if common:
            if not os.path.isabs(common):
                common = os.path.normpath(os.path.join(gitdir, common))
            if os.path.basename(common) == ".git":
                return os.path.dirname(common)
            return common
    parent = os.path.dirname(gitdir)
    if os.path.basename(parent) == "worktrees":
        git_main = os.path.dirname(parent)
        if os.path.basename(git_main) == ".git":
            return os.path.dirname(git_main)
    return None


# ---- clean ----------------------------------------------------------------------------
def _clean_tree(entry: dict, days: Optional[int], now: float, do_it: bool, trash_root: str,
                agent: str = "", imported: Optional[Dict[str, set]] = None):
    root = entry["path"]
    if not os.path.exists(root):
        return [], 0, "not_found", []
    if agent in ("minimax", "opencode"):
        return [], 0, "never", []
    if days is None:
        if do_it:
            dest = os.path.join(trash_root, entry["id"], os.path.basename(os.path.normpath(root)))
            _relocate(root, dest)
        return [root], entry["bytes"], None, []
    logs = None
    if entry.get("kind") == "sessions":
        logs = _log_paths(agent, root)
    log_set = set(os.path.normpath(path) for path in logs) if logs is not None else None
    known = (imported or {}).get(agent) or set()
    files = _files_older_than(root, now, days)
    movable = []
    file_skips = []
    for path, nbytes, rel in files:
        norm = os.path.normpath(path)
        if log_set is not None and norm in log_set and path not in known and norm not in known:
            file_skips.append({"id": path, "reason": "not_imported"})
            continue
        movable.append((path, nbytes, rel))
    if not movable and not file_skips:
        return [], 0, "newer_than_cutoff", []
    moved = []
    freed = 0
    for path, nbytes, rel in movable:
        if do_it:
            _relocate(path, os.path.join(trash_root, entry["id"], rel))
        moved.append(path)
        freed += nbytes
    return moved, freed, None, file_skips


def _clean_worktree(entry: dict, days: Optional[int], now: float, do_it: bool):
    path = entry["path"]
    if not os.path.exists(path):
        return [], 0, "not_found"
    if days is not None and _has_newer_file(path, now, days):
        return [], 0, "newer_than_cutoff"
    if not do_it:
        return [path], entry["bytes"], None
    main = _main_repo(path)
    if not main:
        return [], 0, "not_a_worktree"
    try:
        subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", "-C", main, "worktree", "remove", path],
            check=True, capture_output=True, text=True, timeout=120, env=_git_env(),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return [], 0, "worktree_remove_failed"
    return [path], entry["bytes"], None


def _files_older_than(root: str, now: float, days: int) -> List[Tuple[str, int, str]]:
    limit = days * 86400
    found = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if now - st.st_mtime >= limit:
                found.append((path, int(st.st_blocks) * 512, os.path.relpath(path, root)))
    return found


def _has_newer_file(root: str, now: float, days: int) -> bool:
    limit = days * 86400
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.lstat(path)
            except OSError:
                continue
            if now - st.st_mtime < limit:
                return True
    return False


def _relocate(src: str, dst: str) -> None:
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        os.rename(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(src, dst)


def _refused(path: str) -> bool:
    norm = _norm(path)
    home = _norm(os.path.expanduser("~"))
    banned = {"/", home, "/tmp", "/private", "/private/tmp", "/var", "/Users"}
    return norm in banned


def _parents(paths: List[str]) -> List[str]:
    found = []
    for path in paths:
        parent = os.path.dirname(os.path.normpath(path))
        if parent and parent not in found:
            found.append(parent)
    return found


def _isdir(path: str) -> bool:
    try:
        return os.path.isdir(path)
    except OSError:
        return False


def _norm(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env
