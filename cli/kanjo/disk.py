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
import subprocess
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .cache import _signature
from .ledger import Ledger
from .sources import antigravity, claude, codex
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
LABELS["grok"] = "Grok"
LABELS["claude-desktop"] = "Claude Desktop"
AGENT_ORDER = ["claude", "codex", "antigravity", "grok", "claude-desktop"]
_PARSERS = {"claude": claude, "codex": codex, "antigravity": antigravity}
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
        "claude_app": os.path.expanduser(
            os.environ.get("KANJO_CLAUDE_APP_CACHE") or "~/Library/Application Support/Claude"),
    }


def measure(path: str, now: float, exclude: Optional[List[str]] = None) -> dict:
    """Allocated bytes (``st_blocks * 512``) and file count under ``path``.

    Directories count toward bytes, not ``files``. Symlinks are not followed.
    Permission errors are skipped and counted in ``errors``. ``active`` is true
    when any file or directory inside was modified in the last 24 hours.
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
        note(os.lstat(path), False)
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
                ep = _norm(ent.path)
                if ep in excluded:
                    continue
                try:
                    st = ent.stat(follow_symlinks=False)
                except OSError:
                    errors += 1
                    continue
                if ent.is_symlink():
                    note(st, True)
                    continue
                if ent.is_dir(follow_symlinks=False):
                    note(st, False)
                    stack.append(ent.path)
                    continue
                note(st, True)
    active = newest is not None and (now - newest) < ACTIVE_SECONDS
    return {"bytes": total, "files": files, "oldest": oldest, "newest": newest, "errors": errors, "active": active}


def report(roots: Optional[dict] = None, now: Optional[float] = None, ledger: Optional[Ledger] = None) -> dict:
    """CONTRACT.md section 10 document. Reads the ledger; does not write it."""
    now = time.time() if now is None else now
    roots = default_roots() if roots is None else roots
    ledger = ledger or Ledger()
    grouped = _collect(roots, now, ledger.signatures_by_path())
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
    return {
        "schema_version": 1,
        "generated_at": iso_utc(now),
        "total_bytes": total,
        "reclaimable_bytes": reclaim,
        "agents": agents,
    }


def clean(ids: List[str], older_than_days: Optional[int] = None, dry_run: bool = False, yes: bool = False,
          now: Optional[float] = None, roots: Optional[dict] = None, trash_dir: Optional[str] = None,
          ledger: Optional[Ledger] = None) -> dict:
    """Move ``ids`` into the Trash. Without ``yes``, or with ``dry_run``, nothing is moved.

    ``older_than_days`` keeps files newer than that many days. Worktrees are removed
    as a whole (only when every file is old enough) via ``git worktree remove``.
    """
    now = time.time() if now is None else now
    doc = report(roots=roots, now=now, ledger=ledger)
    by_id = {entry["id"]: entry for agent in doc["agents"] for entry in agent["entries"]}
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
        if entry["blocked"]:
            skipped.append({"id": eid, "reason": ",".join(entry["blocked"])})
            continue
        try:
            if entry["kind"] == "worktrees":
                part_moved, part_freed, reason = _clean_worktree(entry, older_than_days, now, do_it)
            else:
                part_moved, part_freed, reason = _clean_tree(entry, older_than_days, now, do_it, trash_root)
        except OSError:
            skipped.append({"id": eid, "reason": "move_failed"})
            continue
        if reason:
            skipped.append({"id": eid, "reason": reason})
            continue
        moved.extend(part_moved)
        freed += part_freed
    return {"moved": moved, "freed_bytes": freed, "skipped": skipped}


# ---- scanning targets -----------------------------------------------------------------
def _collect(roots: dict, now: float, sigs: Dict[str, list]) -> Dict[str, List[dict]]:
    grouped: Dict[str, List[dict]] = {}
    used = set()

    def add(agent: str, entry: dict) -> None:
        grouped.setdefault(agent, []).append(entry)
        used.add(entry["id"])

    def take_id(eid: str) -> str:
        if eid not in used:
            return eid
        n = 2
        while "%s:%d" % (eid, n) in used:
            n += 1
        return "%s:%d" % (eid, n)

    projects = list(roots.get("claude_projects") or [])
    for path in projects:
        if not _isdir(path):
            continue
        add("claude", _sessions_entry("claude", path, now, sigs, used))
    for parent in _parents(projects):
        for name, eid in (("shell-snapshots", "claude:shell-snapshots"), ("debug", "claude:debug")):
            path = os.path.join(parent, name)
            if _isdir(path):
                add("claude", _plain_entry("claude", take_id(eid), "cache", path, now, []))
    scratch = roots.get("scratch")
    if scratch and _isdir(scratch):
        measured = measure(scratch, now)
        blocked = ["active"] if measured["active"] else []
        add("claude", _make("claude:scratch", "scratch", scratch, measured, blocked))

    codex_dirs = list(roots.get("codex_dirs") or [])
    for path in codex_dirs:
        if not _isdir(path):
            continue
        add("codex", _sessions_entry("codex", path, now, sigs, used))
    for parent in _parents(codex_dirs):
        wt_root = os.path.join(parent, "worktrees")
        if _isdir(wt_root):
            for rel, wpath in _find_worktrees(wt_root):
                measured = measure(wpath, now)
                blocked = []
                if _worktree_dirty(wpath):
                    blocked.append("uncommitted_changes")
                if measured["active"]:
                    blocked.append("active")
                add("codex", _make(take_id("codex:worktree:" + rel), "worktrees", wpath, measured, blocked))
        logs = os.path.join(parent, "logs")
        if _isdir(logs):
            add("codex", _plain_entry("codex", take_id("codex:logs"), "cache", logs, now, []))

    agy_dirs = list(roots.get("antigravity_dirs") or [])
    for path in agy_dirs:
        if not _isdir(path):
            continue
        add("antigravity", _sessions_entry("antigravity", path, now, sigs, used))
    for parent in _parents(agy_dirs):
        brain = os.path.join(parent, "brain")
        if _isdir(brain):
            scratches = _brain_scratches(brain)
            for brain_id, spath in scratches:
                measured = measure(spath, now)
                blocked = ["active"] if measured["active"] else []
                add("antigravity", _make(take_id("antigravity:scratch:" + brain_id), "scratch", spath, measured, blocked))
            measured = measure(brain, now, exclude=[p for _bid, p in scratches])
            add("antigravity", _make(take_id("antigravity:memory"), "memory", brain, measured, []))
        cache = os.path.join(parent, "cache")
        if _isdir(cache):
            add("antigravity", _plain_entry("antigravity", take_id("antigravity:cache"), "cache", cache, now, []))

    grok = roots.get("grok")
    if grok:
        sessions = os.path.join(grok, "sessions")
        if _isdir(sessions):
            note = "Grok sessions. Kanjo does not parse Grok yet, so this stays not_imported."
            add("grok", _plain_entry("grok", take_id("grok:sessions"), "sessions", sessions, now,
                                     ["not_imported"], note=note))
        bundled = os.path.join(grok, "bundled")
        if _isdir(bundled):
            add("grok", _plain_entry("grok", take_id("grok:bundled"), "other", bundled, now, []))

    app = roots.get("claude_app")
    if app:
        for name, eid, note in (
            ("Cache", "claude-desktop:cache", "Claude desktop app cache. Safe to delete."),
            ("Code Cache", "claude-desktop:code-cache", "Claude desktop code cache. Safe to delete."),
            ("GPUCache", "claude-desktop:gpucache", "Claude desktop GPU cache. Safe to delete."),
        ):
            path = os.path.join(app, name)
            if _isdir(path):
                add("claude-desktop", _plain_entry("claude-desktop", take_id(eid), "cache", path, now, [], note=note))
    return grouped


def _sessions_entry(agent: str, path: str, now: float, sigs: Dict[str, list], used: set) -> dict:
    measured = measure(path, now)
    blocked = [] if _logs_imported(agent, path, sigs) else ["not_imported"]
    return _make(_session_id(agent, path, used), "sessions", path, measured, blocked)


def _plain_entry(agent: str, eid: str, kind: str, path: str, now: float, blocked: List[str],
                 note: Optional[str] = None) -> dict:
    return _make(eid, kind, path, measure(path, now), blocked, note=note)


def _make(eid: str, kind: str, path: str, measured: dict, blocked: List[str], note: Optional[str] = None) -> dict:
    return {
        "id": eid,
        "kind": kind,
        "path": path,
        "bytes": measured["bytes"],
        "files": measured["files"],
        "oldest": local_day(measured["oldest"]) if measured["oldest"] is not None else None,
        "newest": local_day(measured["newest"]) if measured["newest"] is not None else None,
        "deletable": DELETABLE[kind],
        "blocked": list(blocked),
        "note": note or NOTES[kind],
        "skipped_errors": measured["errors"],
    }


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


def _logs_imported(agent: str, root: str, sigs: Dict[str, list]) -> bool:
    module = _PARSERS.get(agent)
    if module is None:
        return False
    for path, _parent in module.discover([root]):
        sig = _signature(path)
        known = sigs.get(path) or []
        if sig not in known:
            return False
    return True


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
def _clean_tree(entry: dict, days: Optional[int], now: float, do_it: bool, trash_root: str):
    root = entry["path"]
    if not os.path.exists(root):
        return [], 0, "not_found"
    if days is None:
        if do_it:
            dest = os.path.join(trash_root, entry["id"], os.path.basename(os.path.normpath(root)))
            _relocate(root, dest)
        return [root], entry["bytes"], None
    files = _files_older_than(root, now, days)
    if not files:
        return [], 0, "newer_than_cutoff"
    moved = []
    freed = 0
    for path, nbytes, rel in files:
        if do_it:
            _relocate(path, os.path.join(trash_root, entry["id"], rel))
        moved.append(path)
        freed += nbytes
    return moved, freed, None


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
