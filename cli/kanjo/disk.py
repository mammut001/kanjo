"""Disk usage of local AI tools, and a Trash-only clean.

``kanjo disk`` reports bytes with ``st_blocks * 512`` (actual allocated space).
``kanjo disk clean`` moves files into ``~/.Trash/kanjo-<timestamp>/`` and never
unlinks them; on Windows it hands them to the Recycle Bin (``SHFileOperationW``)
instead and reports ``"Recycle Bin"`` as the trash folder. Git worktrees are
removed with ``git worktree remove`` instead. Nothing is moved unless ``--yes``
is passed. The UI only calls this command.
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

from . import disk_cache, winsupport
from .ledger import Ledger, paths_of
from .sources import (
    antigravity, claude, codebuddy, codex, copilot, deepseek_harness,
    devin, grok_bot, hermes, kimicode, mimocode, minimax, musecode,
    omp, openclaw, opencode, pi, prime_agent, qoder_ide, qodercli,
    qodercli_cn, qoderwork, qwenwork, workbuddy, workbuddy_ai, zcode,
)
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
AGENT_ORDER = [
    "claude", "codex", "antigravity", "grok", "qwen", "commandcode", "minimax",
    "opencode", "copilot", "pi", "workbuddy", "workbuddy_ai", "grok_bot",
    "qoderwork", "qodercli", "qodercli_cn", "zcode", "kimicode", "musecode",
    "codebuddy", "qoder_ide", "hermes", "openclaw", "devin", "mimocode",
    "prime_agent", "omp", "deepseek_harness", "qwenwork",
    "claude-desktop",
]
_PARSERS = {
    "claude": claude,
    "codex": codex,
    "antigravity": antigravity,
    "minimax": minimax,
    "opencode": opencode,
    "copilot": copilot,
    "pi": pi,
    "workbuddy": workbuddy,
    "workbuddy_ai": workbuddy_ai,
    "qwenwork": qwenwork,
    "grok_bot": grok_bot,
    "qoderwork": qoderwork,
    "qodercli": qodercli,
    "qodercli_cn": qodercli_cn,
    "zcode": zcode,
    "kimicode": kimicode,
    "musecode": musecode,
    "codebuddy": codebuddy,
    "qoder_ide": qoder_ide,
    "hermes": hermes,
    "openclaw": openclaw,
    "devin": devin,
    "mimocode": mimocode,
    "prime_agent": prime_agent,
    "omp": omp,
    "deepseek_harness": deepseek_harness,
}
_OLDER = re.compile(r"^(\d+)d$")


def parse_older_than(text: str) -> int:
    match = _OLDER.match(text or "")
    if not match:
        raise ValueError("expected Nd, for example 30d")
    return int(match.group(1))


def trash_base() -> str:
    """``$KANJO_TRASH_DIR`` or ``~/.Trash`` (POSIX only; Windows uses the Recycle Bin)."""
    explicit = os.environ.get("KANJO_TRASH_DIR")
    if explicit:
        return os.path.expanduser(explicit)
    return os.path.expanduser("~/.Trash")


def use_recycle_bin(explicit_trash_dir: Optional[str] = None) -> bool:
    """True when clean should hand items to the Recycle Bin instead of a Trash folder.

    Windows only, and only when nothing pinned a Trash directory: ``trash_dir`` and
    ``KANJO_TRASH_DIR`` are explicit targets (tests and ops use them to keep the
    move inside a temp tree), and an explicit target always wins.
    """
    if not winsupport.is_windows():
        return False
    return not explicit_trash_dir and not os.environ.get("KANJO_TRASH_DIR")


def _default_scratch() -> str:
    """Claude Code's scratch dir: ``/tmp/claude-<uid>``, or ``%TEMP%\\claude-<uid>``."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    if winsupport.is_windows():
        base = winsupport.temp_dirs()
        return winsupport.join(base[0], "claude-%s" % uid) if base else winsupport.join(
            winsupport.local_app_data() or os.path.expanduser("~"), "Temp", "claude-%s" % uid)
    return "/tmp/claude-%s" % uid


# Characters that have no legal spelling in a Windows file name; ':' is the one
# that shows up in entry ids (``claude:shell-snapshots``).
_ILLEGAL_WIN_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _trash_component(name: str) -> str:
    """One path component of the Trash destination, legal on this platform.

    Entry ids contain ``:``, which Windows reserves for drive letters, so a pinned
    Trash folder (``--trash-dir`` / ``KANJO_TRASH_DIR``) could not be created there.
    POSIX names are returned exactly as before.
    """
    if not winsupport.is_windows():
        return name
    safe = _ILLEGAL_WIN_NAME.sub("-", name).strip(" .")
    return safe or "-"


def default_roots() -> dict:
    """Directories ``kanjo disk`` scans. Parser overrides relocate the whole tool root.

    ``KANJO_CLAUDE_DIR`` / ``KANJO_CODEX_DIR`` / ``KANJO_ANTIGRAVITY_DIR`` replace the
    log directories the parsers use. Shell snapshots, debug logs, Codex worktrees
    and logs, and the Antigravity brain and cache are siblings of those directories
    (so the default layout is unchanged). ``KANJO_SCRATCH_DIR``, ``KANJO_GROK_DIR``
    and ``KANJO_CLAUDE_APP_CACHE`` exist so tests never touch the real machine.

    On Windows the defaults follow each tool's own layout: dot-dirs stay in
    ``%USERPROFILE%``, Electron apps move from ``~/Library/Application Support`` to
    ``%APPDATA%``, XDG data dirs to ``%LOCALAPPDATA%`` (OpenCode keeps
    ``%USERPROFILE%\\.local\\share\\opencode``), and macOS-only desktop apps are skipped.
    """
    win = winsupport.is_windows()

    def _dir(env_name: str, mac_default: str, windows_default: Optional[str] = None) -> Optional[str]:
        """An explicit env override always wins; otherwise the platform default.

        ``windows_default=None`` marks a macOS-only tool: nothing is scanned on
        Windows unless the user points ``KANJO_*_DIR`` at it.
        """
        explicit = os.environ.get(env_name)
        if explicit:
            return winsupport.expanduser(explicit)
        if os.environ.get("KANJO_DATA_DIR"):
            return None
        if win:
            # The Windows defaults are written "~/.tool" like the macOS ones; they
            # must be expanded or every scan below looks at a literal "~" folder.
            return winsupport.expanduser(windows_default) if windows_default else None
        return winsupport.expanduser(mac_default)

    opencode_default = (winsupport.join(winsupport.user_profile() or "", ".local", "share", "opencode")
                        if win else "~/.local/share/opencode")
    claude_app_default = (winsupport.join(winsupport.app_data() or "", "Claude")
                          if win else "~/Library/Application Support/Claude")
    devin_default = winsupport.join(winsupport.local_data_dir("devin"), "cli") if win else "~/.local/share/devin/cli"
    musecode_default = winsupport.local_data_dir("muse") if win else "~/.local/share/muse"
    return {
        "claude_projects": env_dirs("KANJO_CLAUDE_DIR", ["~/.claude/projects"]),
        "scratch": winsupport.expanduser(os.environ.get("KANJO_SCRATCH_DIR") or _default_scratch()),
        "codex_dirs": env_dirs("KANJO_CODEX_DIR", ["~/.codex/sessions", "~/.codex/archived_sessions"]),
        "antigravity_dirs": env_dirs("KANJO_ANTIGRAVITY_DIR", [
            "~/.gemini/antigravity-cli/conversations",
            "~/.gemini/antigravity/conversations",
            "~/.gemini/antigravity-ide/conversations",
            "~/.gemini/gemini-cli/conversations",
        ]),
        "grok": _dir("KANJO_GROK_DIR", "~/.grok", "~/.grok"),
        "qwen": _dir("KANJO_QWEN_DIR", "~/.qwen", "~/.qwen"),
        "commandcode": _dir("KANJO_COMMANDCODE_DIR", "~/.commandcode", "~/.commandcode"),
        "claude_app": winsupport.expanduser(
            os.environ.get("KANJO_CLAUDE_APP_CACHE") or claude_app_default),
        "minimax": _dir("KANJO_MINIMAX_DIR", "~/.minimax", "~/.minimax"),
        "opencode": _dir("KANJO_OPENCODE_DIR", "~/.local/share/opencode", opencode_default),
        "copilot": _dir("KANJO_COPILOT_DIR", "~/.copilot", "~/.copilot"),
        "pi": winsupport.expanduser(os.environ["KANJO_PI_DIR"]) if os.environ.get("KANJO_PI_DIR") else (
            winsupport.expanduser(os.environ["PI_CODING_AGENT_DIR"]) if os.environ.get("PI_CODING_AGENT_DIR") else (
                winsupport.expanduser(os.environ["PI_CODING_AGENT_SESSION_DIR"]) if os.environ.get("PI_CODING_AGENT_SESSION_DIR") else (
                    None if os.environ.get("KANJO_DATA_DIR") else winsupport.expanduser("~/.pi")
                )
            )
        ),
        "workbuddy": _dir("KANJO_WORKBUDDY_DIR", "~/.workbuddy", "~/.workbuddy"),
        "workbuddy_ai": _dir("KANJO_WORKBUDDY_AI_DIR", "~/.workbuddy-ai", "~/.workbuddy-ai"),
        "qwenwork": winsupport.expanduser(os.environ["KANJO_QWENWORK_DIR"]) if os.environ.get("KANJO_QWENWORK_DIR") else (
            winsupport.expanduser(os.environ["TOKEI_QWENWORK_HOME"]) if os.environ.get("TOKEI_QWENWORK_HOME") else (
                None if os.environ.get("KANJO_DATA_DIR") else winsupport.expanduser("~/.qwenworkcn")
            )
        ),
        "grok_bot": _dir("KANJO_GROK_BOT_DIR", "~/Library/Application Support/Grok Bot"),
        "qoderwork": _dir("KANJO_QODERWORK_DIR", "~/Library/Application Support/QoderWork"),
        "qodercli": _dir("KANJO_QODERCLI_DIR", "~/.qoder", "~/.qoder"),
        "qodercli_cn": _dir("KANJO_QODERCLI_CN_DIR", "~/.qoder-cn", "~/.qoder-cn"),
        "zcode": _dir("KANJO_ZCODE_DIR", "~/.zcode", "~/.zcode"),
        "kimicode": _dir("KANJO_KIMICODE_DIR", "~/.kimi-code", "~/.kimi-code"),
        "musecode": _dir("KANJO_MUSECODE_DIR", "~/.local/share/muse", musecode_default),
        "codebuddy": _dir("KANJO_CODEBUDDY_DIR", "~/.codebuddy", "~/.codebuddy"),
        "qoder_ide": _dir("KANJO_QODER_IDE_DIR", "~/Library/Application Support/Qoder/SharedClientCache/cache/db"),
        "hermes": _dir("KANJO_HERMES_DIR", "~/.hermes", "~/.hermes"),
        "openclaw": _dir("KANJO_OPENCLAW_DIR", "~/.openclaw", "~/.openclaw"),
        "devin": _dir("KANJO_DEVIN_DIR", "~/.local/share/devin/cli", devin_default),
        "mimocode": _dir("KANJO_MIMOCODE_DIR", "~/Library/Application Support/mimocode"),
        "prime_agent": _dir("KANJO_PRIME_AGENT_DIR", "~/.prime/agent/sessions", "~/.prime/agent/sessions"),
        "omp": _dir("KANJO_OMP_DIR", "~/.omp/agent/sessions", "~/.omp/agent/sessions"),
        "deepseek_harness": _dir("KANJO_DEEPSEEK_HARNESS_DIR", "~/.tokei/cache/dsh-sessions", "~/.tokei/cache/dsh-sessions"),
    }


HEAVY_DIRS = {"node_modules", ".build", "DerivedData", ".venv", "target", "Pods"}


def _stat_bytes(st) -> int:
    if hasattr(st, "st_blocks"):
        return int(st.st_blocks) * 512
    return int(getattr(st, "st_size", 0))


def _measure_heavy_dir(dir_path: str, dir_st) -> Tuple[int, int, Optional[float], Optional[float], int]:
    """Measure a heavy build/dependency directory with du -sk and fast file count.
    Returns (bytes, files, oldest, newest, errors).
    """
    errors = 0
    total_bytes = None
    if not winsupport.is_windows():
        # Windows has no du(1); the scandir walk below measures the directory instead.
        try:
            proc = subprocess.run(["du", "-sk", dir_path], capture_output=True, timeout=30)
            if proc.returncode == 0:
                first_col = proc.stdout.split(None, 1)[0]
                total_bytes = int(first_col) * 1024
        except Exception:
            pass

    file_count = 0
    oldest = dir_st.st_mtime
    newest = dir_st.st_mtime

    if total_bytes is not None:
        file_count = 1
        return (total_bytes, file_count, oldest, newest, errors)

    total_bytes = _stat_bytes(dir_st)
    stack = [dir_path]
    while stack:
        cur = stack.pop()
        try:
            it = os.scandir(cur)
        except OSError:
            errors += 1
            continue
        with it:
            for ent in it:
                try:
                    st = ent.stat(follow_symlinks=False)
                except OSError:
                    errors += 1
                    continue
                if stat.S_ISDIR(st.st_mode):
                    total_bytes += _stat_bytes(st)
                    stack.append(ent.path)
                else:
                    total_bytes += _stat_bytes(st)
                    file_count += 1
                ts = st.st_mtime
                if oldest is None or ts < oldest:
                    oldest = ts
                if newest is None or ts > newest:
                    newest = ts
    return (total_bytes, file_count, oldest, newest, errors)


def _measure_heavy_dirs(dirs: List[Tuple[str, Any]]) -> Tuple[int, int, Optional[float], Optional[float], int]:
    """Measure multiple heavy directories using batched du -sk calls."""
    if not dirs:
        return 0, 0, None, None, 0
    total_bytes = 0
    total_files = 0
    errors = 0
    oldest = None
    newest = None

    paths = [p for p, _ in dirs]
    measured_paths: Dict[str, int] = {}

    if not winsupport.is_windows():
        try:
            proc = subprocess.run(["du", "-sk"] + paths, capture_output=True, timeout=60)
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    parts = line.split(b"\t", 1)
                    if len(parts) == 2:
                        try:
                            measured_paths[parts[1].decode("utf-8")] = int(parts[0]) * 1024
                        except (ValueError, UnicodeDecodeError):
                            pass
        except Exception:
            pass

    for p, st in dirs:
        ts = st.st_mtime
        if oldest is None or ts < oldest:
            oldest = ts
        if newest is None or ts > newest:
            newest = ts

        b = measured_paths.get(p)
        if b is not None:
            total_bytes += b
            total_files += 1
        else:
            h_b, h_f, h_old, h_new, h_err = _measure_heavy_dir(p, st)
            total_bytes += h_b
            total_files += h_f
            errors += h_err
            if h_old is not None and (oldest is None or h_old < oldest):
                oldest = h_old
            if h_new is not None and (newest is None or h_new > newest):
                newest = h_new

    return total_bytes, total_files, oldest, newest, errors


def measure(path: str, now: float, exclude: Optional[List[str]] = None,
            _root_stat=None, _submit=None) -> dict:
    """Allocated bytes (``st_blocks * 512``) and file count under ``path``.

    Directories count toward bytes, not ``files``. Symlinks are not followed.
    Permission errors are skipped and counted in ``errors``. ``active`` is true
    when any file or directory inside was modified in the last 24 hours.
    Internally, ``_submit`` delegates first-level directories to the report pool;
    ``_root_stat`` reuses their stat result so each directory is counted once.
    """
    path = _norm(path)
    excluded = set(_norm(p) for p in (exclude or []))
    total = 0
    files = 0
    errors = 0
    oldest = None
    newest = None

    try:
        root_st = os.lstat(path) if _root_stat is None else _root_stat
        total += _stat_bytes(root_st)
        ts = root_st.st_mtime
        oldest = ts
        newest = ts
    except OSError:
        errors += 1
        return {"bytes": 0, "files": 0, "oldest": None, "newest": None, "errors": errors, "active": False}

    stack = [path]
    seen = set()
    heavy_dirs: List[Tuple[str, Any]] = []

    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        try:
            iterator = os.scandir(current)
        except OSError:
            errors += 1
            continue
        with iterator:
            for ent in iterator:
                if excluded and ent.path in excluded:
                    continue
                try:
                    st = ent.stat(follow_symlinks=False)
                except OSError:
                    errors += 1
                    continue
                mode = st.st_mode
                if (mode & 0o170000) == 0o040000:  # stat.S_ISDIR
                    if _submit is not None:
                        _submit(ent.path, st)
                    elif ent.name in HEAVY_DIRS:
                        heavy_dirs.append((ent.path, st))
                    else:
                        total += _stat_bytes(st)
                        ts = st.st_mtime
                        if oldest is None or ts < oldest:
                            oldest = ts
                        if newest is None or ts > newest:
                            newest = ts
                        stack.append(ent.path)
                    continue
                total += _stat_bytes(st)
                files += 1
                ts = st.st_mtime
                if oldest is None or ts < oldest:
                    oldest = ts
                if newest is None or ts > newest:
                    newest = ts

    if heavy_dirs:
        h_bytes, h_files, h_old, h_new, h_err = _measure_heavy_dirs(heavy_dirs)
        total += h_bytes
        files += h_files
        errors += h_err
        if h_old is not None and (oldest is None or h_old < oldest):
            oldest = h_old
        if h_new is not None and (newest is None or h_new > newest):
            newest = h_new

    active = newest is not None and (now - newest) < ACTIVE_SECONDS
    return {"bytes": total, "files": files, "oldest": oldest, "newest": newest, "errors": errors, "active": active}


def report(roots: Optional[dict] = None, now: Optional[float] = None, ledger: Optional[Ledger] = None,
           max_age: float = 600, rescan: bool = False) -> dict:
    """CONTRACT.md section 10 document. Reads the ledger; caches the report."""
    started = time.monotonic()
    now = time.time() if now is None else now
    roots = default_roots() if roots is None else roots
    valid_entries = {}
    if not rescan:
        cached, valid_entries, wt_cache = disk_cache.load_cached_report(roots, now, max_age)
        if cached is not None:
            return cached
        if wt_cache:
            for k, v in wt_cache.items():
                parts = k.split("\0")
                if len(parts) == 3:
                    try:
                        _WORKTREE_DIRTY_CACHE[(parts[0], int(parts[1]), int(parts[2]))] = v
                    except ValueError:
                        pass
    ledger = ledger or Ledger()
    with ThreadPoolExecutor(max_workers=min(2, os.cpu_count() or 1)) as executor:
        grouped = _collect(roots, now, _imported_index(ledger), executor, valid_entries=valid_entries)
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
    wt_dict = {("%s\0%d\0%d" % (k[0], k[1], k[2])): v for k, v in _WORKTREE_DIRTY_CACHE.items()}
    disk_cache.save(doc, roots, worktrees=wt_dict)
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

    On Windows things go to the Recycle Bin instead of ``~/.Trash``, and the result
    then carries ``"trash_dir": "Recycle Bin"``. An explicit ``trash_dir`` (or
    ``KANJO_TRASH_DIR``) still pins a real folder, so a caller that wants the move
    confined to a temp tree keeps working on Windows.
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
    recycle_bin = use_recycle_bin(trash_dir)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    trash_root = "" if recycle_bin else os.path.join(trash_dir or trash_base(), "kanjo-" + stamp)
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
                    entry, older_than_days, now, do_it, trash_root, agent=agent, imported=imported,
                    recycle_bin=recycle_bin)
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
    result = {"moved": moved, "freed_bytes": freed, "skipped": skipped}
    if winsupport.is_windows():
        # On Windows there is no Trash folder unless one was pinned explicitly.
        result["trash_dir"] = trash_root if trash_root else winsupport.RECYCLE_BIN
    return result


# ---- scanning targets -----------------------------------------------------------------
def _collect(roots: dict, now: float, imported: Dict[str, set],
             executor: ThreadPoolExecutor,
             valid_entries: Optional[Dict[str, dict]] = None) -> Dict[str, List[dict]]:
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
        cached_e = valid_entries.get(eid) if valid_entries else None
        if cached_e is not None and cached_e.get("path") == path:
            pending.append((agent, eid, kind, path, blocked or [], note, None, None, None, None, deletable, cached_e))
            return
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
        pending.append((agent, eid, kind, path, blocked or [], note, counts, dirty, shallow, parts, deletable, None))

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

    pi_root = roots.get("pi")
    if pi_root and _isdir(pi_root):
        pi_sessions = None
        for cand in [os.path.join(pi_root, "agent", "sessions"), os.path.join(pi_root, "sessions"), pi_root]:
            if _isdir(cand) and (cand.endswith("sessions") or os.path.basename(cand) == "sessions"):
                pi_sessions = cand
                break
        if pi_sessions:
            add("pi", take_id("pi:sessions"), "sessions", pi_sessions,
                note="Pi agent sessions.")

    wb_root = roots.get("workbuddy")
    if wb_root and _isdir(wb_root):
        cand = os.path.join(wb_root, "projects") if os.path.basename(wb_root) != "projects" and _isdir(os.path.join(wb_root, "projects")) else wb_root
        add("workbuddy", take_id("workbuddy:sessions"), "sessions", cand, note="WorkBuddy sessions.")

    wb_ai_root = roots.get("workbuddy_ai")
    if wb_ai_root and _isdir(wb_ai_root):
        cand = os.path.join(wb_ai_root, "projects") if os.path.basename(wb_ai_root) != "projects" and _isdir(os.path.join(wb_ai_root, "projects")) else wb_ai_root
        add("workbuddy_ai", take_id("workbuddy_ai:sessions"), "sessions", cand, note="WorkBuddy Intl. sessions.")

    qwork_root = roots.get("qwenwork")
    if qwork_root and _isdir(qwork_root):
        cand = os.path.join(qwork_root, "logs", "sessions") if os.path.basename(qwork_root) != "sessions" and _isdir(os.path.join(qwork_root, "logs", "sessions")) else qwork_root
        add("qwenwork", take_id("qwenwork:sessions"), "sessions", cand, note="QwenWork sessions.")

    gb_root = roots.get("grok_bot")
    if gb_root and _isdir(gb_root):
        cand = os.path.join(gb_root, "sand-client-persistence") if os.path.basename(gb_root) != "sand-client-persistence" and _isdir(os.path.join(gb_root, "sand-client-persistence")) else gb_root
        add("grok_bot", take_id("grok_bot:sessions"), "sessions", cand, note="Grok Bot sessions.")

    qw_root = roots.get("qoderwork")
    if qw_root and (_isdir(qw_root) or os.path.isfile(qw_root)):
        db = os.path.join(qw_root, "data", "agents.db") if _isdir(qw_root) and _isdir(os.path.join(qw_root, "data")) else (os.path.join(qw_root, "agents.db") if _isdir(qw_root) else qw_root)
        if not os.path.isfile(db) and _isdir(qw_root):
            cand_db = os.path.join(qw_root, "data", "sqlite.db")
            if os.path.isfile(cand_db):
                db = cand_db
            else:
                db = os.path.join(qw_root, "sqlite.db")
        if os.path.isfile(db) or _isdir(qw_root):
            add("qoderwork", take_id("qoderwork:sessions"), "sessions", qw_root,
                note="QoderWork SQLite database. DB-backed sessions are never deleted by disk clean.",
                deletable="never")

    qc_root = roots.get("qodercli")
    if qc_root and _isdir(qc_root):
        cand = os.path.join(qc_root, "projects") if os.path.basename(qc_root) != "projects" and _isdir(os.path.join(qc_root, "projects")) else qc_root
        add("qodercli", take_id("qodercli:sessions"), "sessions", cand, note="Qoder CLI sessions.")

    qc_cn_root = roots.get("qodercli_cn")
    if qc_cn_root and _isdir(qc_cn_root):
        cand = os.path.join(qc_cn_root, "projects") if os.path.basename(qc_cn_root) != "projects" and _isdir(os.path.join(qc_cn_root, "projects")) else qc_cn_root
        add("qodercli_cn", take_id("qodercli_cn:sessions"), "sessions", cand, note="Qoder CN sessions.")

    zc_root = roots.get("zcode")
    if zc_root and (_isdir(zc_root) or os.path.isfile(zc_root)):
        db = os.path.join(zc_root, "cli", "db", "db.sqlite") if _isdir(zc_root) and _isdir(os.path.join(zc_root, "cli", "db")) else (os.path.join(zc_root, "db.sqlite") if _isdir(zc_root) else zc_root)
        if os.path.isfile(db) or _isdir(zc_root):
            add("zcode", take_id("zcode:sessions"), "sessions", zc_root,
                note="ZCode SQLite database. DB-backed sessions are never deleted by disk clean.",
                deletable="never")

    kc_root = roots.get("kimicode")
    if kc_root and _isdir(kc_root):
        cand = os.path.join(kc_root, "sessions") if os.path.basename(kc_root) != "sessions" and _isdir(os.path.join(kc_root, "sessions")) else kc_root
        add("kimicode", take_id("kimicode:sessions"), "sessions", cand, note="Kimi Code sessions.")

    mc_root = roots.get("musecode")
    if mc_root and _isdir(mc_root):
        cand = os.path.join(mc_root, "sessions") if os.path.basename(mc_root) != "sessions" and _isdir(os.path.join(mc_root, "sessions")) else mc_root
        add("musecode", take_id("musecode:sessions"), "sessions", cand, note="Muse Code sessions.")

    cb_root = roots.get("codebuddy")
    if cb_root and _isdir(cb_root):
        cand = os.path.join(cb_root, "projects") if os.path.basename(cb_root) != "projects" and _isdir(os.path.join(cb_root, "projects")) else cb_root
        add("codebuddy", take_id("codebuddy:sessions"), "sessions", cand, note="CodeBuddy sessions.")

    qi_root = roots.get("qoder_ide")
    if qi_root and (_isdir(qi_root) or os.path.isfile(qi_root)):
        add("qoder_ide", take_id("qoder_ide:sessions"), "sessions", qi_root,
            note="Qoder IDE SQLite database. DB-backed sessions are never deleted by disk clean.",
            deletable="never")

    hm_root = roots.get("hermes")
    if hm_root and (_isdir(hm_root) or os.path.isfile(hm_root)):
        add("hermes", take_id("hermes:sessions"), "sessions", hm_root,
            note="Hermes SQLite database. DB-backed sessions are never deleted by disk clean.",
            deletable="never")

    oc_root = roots.get("openclaw")
    if oc_root and _isdir(oc_root):
        cand = os.path.join(oc_root, "agents") if _isdir(os.path.join(oc_root, "agents")) else oc_root
        add("openclaw", take_id("openclaw:sessions"), "sessions", cand, note="OpenClaw sessions.")

    dv_root = roots.get("devin")
    if dv_root and (_isdir(dv_root) or os.path.isfile(dv_root)):
        add("devin", take_id("devin:sessions"), "sessions", dv_root,
            note="Devin SQLite database. DB-backed sessions are never deleted by disk clean.",
            deletable="never")

    mimo_root = roots.get("mimocode")
    if mimo_root and (_isdir(mimo_root) or os.path.isfile(mimo_root)):
        add("mimocode", take_id("mimocode:sessions"), "sessions", mimo_root,
            note="MiMo Code SQLite database. DB-backed sessions are never deleted by disk clean.",
            deletable="never")

    prime_root = roots.get("prime_agent")
    if prime_root and _isdir(prime_root):
        cand = os.path.join(prime_root, "sessions") if os.path.basename(prime_root) != "sessions" and _isdir(os.path.join(prime_root, "sessions")) else prime_root
        add("prime_agent", take_id("prime_agent:sessions"), "sessions", cand, note="Prime Agent sessions.")

    omp_root = roots.get("omp")
    if omp_root and _isdir(omp_root):
        cand = os.path.join(omp_root, "sessions") if os.path.basename(omp_root) != "sessions" and _isdir(os.path.join(omp_root, "sessions")) else omp_root
        add("omp", take_id("omp:sessions"), "sessions", cand, note="OMP sessions.")

    dsh_root = roots.get("deepseek_harness")
    if dsh_root and _isdir(dsh_root):
        add("deepseek_harness", take_id("deepseek_harness:sessions"), "sessions", dsh_root, note="DeepSeek Harness sessions.")

    # Resolve in discovery order so scheduling never changes ids or JSON ordering.
    for agent, eid, kind, path, blocked, note, counts, dirty, shallow, parts, deletable, cached_e in pending:
        if cached_e is not None:
            grouped.setdefault(agent, []).append(dict(cached_e))
            continue
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
    imported_files = sum(1 for path in logs
                         if path in known or winsupport.normpath(path) in known)
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


_WORKTREE_DIRTY_CACHE: Dict[Tuple[str, int, int], bool] = {}


def _git_head_index_mtimes(path: str) -> Optional[Tuple[int, int]]:
    git_path = os.path.join(path, ".git")
    gitdir = None
    if os.path.isfile(git_path):
        try:
            with open(git_path, "r", encoding="utf-8") as f:
                line = f.read().strip()
            if line.startswith("gitdir:"):
                raw = line.split(":", 1)[1].strip()
                gitdir = raw if os.path.isabs(raw) else os.path.normpath(os.path.join(path, raw))
        except OSError:
            return None
    elif os.path.isdir(git_path):
        gitdir = git_path
    if not gitdir or not os.path.isdir(gitdir):
        return None
    try:
        head_st = os.stat(os.path.join(gitdir, "HEAD"))
        head_mtime = head_st.st_mtime_ns
    except OSError:
        head_mtime = 0
    try:
        index_st = os.stat(os.path.join(gitdir, "index"))
        index_mtime = index_st.st_mtime_ns
    except OSError:
        index_mtime = 0
    return (head_mtime, index_mtime)


def _worktree_dirty(path: str) -> bool:
    """True when ``git status --porcelain`` is non-empty, or git cannot say."""
    mtimes = _git_head_index_mtimes(path)
    if mtimes is not None:
        key = (path, mtimes[0], mtimes[1])
        if key in _WORKTREE_DIRTY_CACHE:
            return _WORKTREE_DIRTY_CACHE[key]
    try:
        proc = subprocess.run(
            ["git", "-c", "core.hooksPath=" + _no_hooks(), "-C", path, "status", "--porcelain"],
            capture_output=True, text=True, encoding="utf-8", timeout=60, env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    if proc.returncode != 0:
        return True
    is_dirty = bool(proc.stdout.strip())
    if mtimes is not None:
        _WORKTREE_DIRTY_CACHE[(path, mtimes[0], mtimes[1])] = is_dirty
    return is_dirty


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
                agent: str = "", imported: Optional[Dict[str, set]] = None,
                recycle_bin: bool = False):
    root = entry["path"]
    if not os.path.exists(root):
        return [], 0, "not_found", []
    if agent in ("minimax", "opencode", "qoderwork", "zcode", "qoder_ide", "hermes", "devin", "mimocode"):
        return [], 0, "never", []

    def _dest(*parts) -> Optional[str]:
        """Trash destination, or None when the Recycle Bin is the target."""
        if recycle_bin:
            return None
        # The first component is the entry id ("claude:shell-snapshots"), which
        # Windows cannot use as a directory name.
        if parts:
            parts = (_trash_component(parts[0]),) + tuple(parts[1:])
        return os.path.join(trash_root, *parts)

    if days is None:
        if do_it:
            _relocate(root, _dest(entry["id"], os.path.basename(os.path.normpath(root))))
        return [root], entry["bytes"], None, []
    logs = None
    if entry.get("kind") == "sessions":
        logs = _log_paths(agent, root)
    # Empty when the entry is not a sessions folder (nothing is a log file then).
    log_set = set(winsupport.normpath(path) for path in logs or ())
    known = (imported or {}).get(agent) or set()
    files = _files_older_than(root, now, days)
    movable = []
    file_skips = []
    for path, nbytes, rel in files:
        norm = winsupport.normpath(path)
        if norm in log_set and path not in known and norm not in known:
            file_skips.append({"id": path, "reason": "not_imported"})
            continue
        movable.append((path, nbytes, rel))
    if not movable and not file_skips:
        return [], 0, "newer_than_cutoff", []
    moved = []
    freed = 0
    locked = []
    for path, nbytes, rel in movable:
        if do_it:
            try:
                _relocate(path, _dest(entry["id"], rel))
            except OSError:
                if not winsupport.is_windows():
                    raise
                # A file held open by a running agent: report that file, keep going.
                locked.append({"id": path, "reason": "move_failed"})
                continue
        moved.append(path)
        freed += nbytes
    return moved, freed, None, file_skips + locked


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
            ["git", "-c", "core.hooksPath=" + _no_hooks(), "-C", main, "worktree", "remove", path],
            check=True, capture_output=True, text=True, encoding="utf-8", timeout=120, env=_git_env(),
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
                found.append((path, _stat_bytes(st), os.path.relpath(path, root)))
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


def _relocate(src: str, dst: Optional[str]) -> None:
    """Move ``src`` aside: into the Trash tree on POSIX, into the Recycle Bin on Windows.

    ``dst`` is the Trash destination and is required on POSIX. On Windows ``dst`` is
    ``None`` when the Recycle Bin is the target (``SHFileOperationW`` picks the name
    and restores the original path); a real ``dst`` still moves the item there, which
    is what an explicitly pinned ``trash_dir`` asks for.
    """
    if winsupport.is_windows() and dst is None:
        code = winsupport.recycle([src])
        if code is None:
            raise OSError(errno.EIO, "Recycle Bin is unavailable", src)
        if code != 0:
            raise OSError(errno.EACCES, "cannot move %s to the Recycle Bin (code %s)" % (src, code), src)
        return
    parent = os.path.dirname(dst)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.move(src, dst)


def _refused(path: str) -> bool:
    norm = _norm(path)
    home = _norm(os.path.expanduser("~"))
    banned = {"/", home, "/tmp", "/private", "/private/tmp", "/var", "/Users"}
    if winsupport.is_windows():
        # Any drive root (C:\), the user profile and the directories Windows needs.
        if re.match(r"^[A-Za-z]:[\\/]?$", norm):
            return True
        for var in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "SYSTEMROOT"):
            value = os.environ.get(var)
            if value:
                banned.add(_norm(value))
    # Windows paths compare case-insensitively; POSIX keys are unchanged.
    return winsupport.normcase_key(norm) in {winsupport.normcase_key(p) for p in banned}


def _parents(paths: List[str]) -> List[str]:
    found = []
    for path in paths:
        parent = winsupport.dirname(winsupport.normpath(path))
        if parent and parent not in found:
            found.append(parent)
    return found


def _isdir(path: str) -> bool:
    try:
        return os.path.isdir(path)
    except OSError:
        return False


def _norm(path: str) -> str:
    """Absolute normalized path (Windows spellings stay Windows on any host)."""
    return winsupport.normpath(winsupport.abspath(path))


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _no_hooks() -> str:
    """``core.hooksPath`` that disables hooks: ``/dev/null`` on POSIX, ``nul`` on Windows."""
    return os.devnull
