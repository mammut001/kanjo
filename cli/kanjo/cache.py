"""Per-file parse cache.

Parsing ~10 GB of logs takes tens of seconds; most files never change after
their session ends. Parsed sessions are cached per file, keyed by size and
mtime (plus the ``-wal`` file for SQLite), in
``$KANJO_CACHE_DIR`` or ``~/.cache/kanjo/parse-cache-v<N>.json``.
Only derived numbers and paths are stored, never conversation text other than
the 80-character session title.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Callable, Dict, List, Optional, Set, Tuple

from .sources.base import Message, ParseError, Session

CACHE_VERSION = 4
REPO_CACHE_VERSION = 2
NEGATIVE_TTL = 600.0  # 10 minutes TTL for negative (no-repo) resolutions
_MSG_FIELDS = ("ts", "model", "input", "output", "cache_read", "cache_write", "cache_write_1h",
               "thinking", "cwd", "branch", "key")


def _cache_dir() -> str:
    explicit = os.environ.get("KANJO_CACHE_DIR")
    if explicit:
        return os.path.expanduser(explicit)
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "kanjo")


def _signature(path: str) -> Optional[list]:
    stat_path = path.split("::", 1)[0] if "::" in path else path
    sig = []
    for p in (stat_path, stat_path + "-wal"):
        try:
            st = os.stat(p)
        except OSError:
            if p == stat_path:
                return None
            sig.append(None)
            continue
        sig.append([st.st_size, st.st_mtime_ns])
    return sig


def _dump_session(s: Session) -> dict:
    return {
        "id": s.id,
        "agent": s.agent,
        "file": s.file,
        "started": s.started,
        "ended": s.ended,
        "origin_ts": s.origin_ts,
        "cwd": s.cwd,
        "branch": s.branch,
        "messages": [
            [
                m.ts,
                m.model,
                m.input,
                m.output,
                m.cache_read,
                m.cache_write,
                m.cache_write_1h,
                m.thinking,
                m.cwd,
                m.branch,
                m.key,
            ]
            for m in s.messages
        ],
        "tool_paths": [list(call) for call in s.tool_paths],
        "subagent_of": s.subagent_of,
        "title": s.title,
        "cwd_counts": dict(s.cwd_counts),
        "remote_hints": dict(s.remote_hints),
    }


def _load_session(d: dict) -> Session:
    msgs = d.get("messages") or []
    s = Session(
        id=d.get("id", ""),
        agent=d.get("agent", ""),
        file=d.get("file", ""),
        started=d.get("started", 0.0),
        ended=d.get("ended", 0.0),
        origin_ts=d.get("origin_ts"),
        cwd=d.get("cwd", ""),
        branch=d.get("branch"),
        tool_paths=d.get("tool_paths") or [],
        subagent_of=d.get("subagent_of"),
        title=d.get("title", ""),
        cwd_counts=d.get("cwd_counts") or {},
        remote_hints=d.get("remote_hints") or {},
    )
    s.messages = [
        Message(*row) if len(row) == 11 else Message(**dict(zip(_MSG_FIELDS, row)))
        for row in msgs
    ]
    return s


class RepoCache:
    """Persistent cache mapping directory/file paths to enclosing git repository resolution.

    Entries:
    - Positive: {"repo": {...}, "dotgit": "<path>", "sig": [<mtime_ns>, <ino>]}
      Validated by checking dotgit exists and its (mtime_ns, ino) matches sig.
    - Negative: {"repo": None, "ts": <timestamp>}
      Validated by TTL (default 10 minutes).
    """

    def __init__(self, directory: Optional[str] = None):
        self.dir = directory or _cache_dir()
        self.path = os.path.join(self.dir, "repo-cache-v%d.json" % REPO_CACHE_VERSION)
        self.entries: Dict[str, dict] = {}
        self.dirty = False
        self._stat_sig_cache: Dict[str, Optional[list]] = {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and data.get("version") == REPO_CACHE_VERSION:
                self.entries = data.get("paths") or {}
        except (OSError, ValueError):
            self.entries = {}

    def get(self, path: str, fs_root: str = "", now: Optional[float] = None) -> Tuple[bool, Optional[dict]]:
        """Return (hit, repo_dict). If hit is True, repo_dict is the serialized RepoInfo
        (or None for a cached negative result). If hit is False, the entry was missing or invalid.
        """
        entry = self.entries.get(path)
        cur = path
        if entry is None:
            while True:
                parent = os.path.dirname(cur)
                if not parent or parent == cur:
                    break
                cur = parent
                cand = self.entries.get(cur)
                if cand is not None and cand.get("repo") is not None:
                    entry = cand
                    break

        if entry is None:
            return False, None

        if entry.get("repo") is None:
            ts = entry.get("ts")
            if ts is not None and isinstance(ts, (int, float)):
                current_time = time.time() if now is None else now
                if current_time - ts < NEGATIVE_TTL:
                    return True, None
            # Expired negative result
            return False, None

        dotgit = entry.get("dotgit")
        sig = entry.get("sig")
        if not dotgit or not sig or not isinstance(sig, list) or len(sig) != 2:
            return False, None

        stat_path = (fs_root + dotgit) if fs_root else dotgit
        if stat_path in self._stat_sig_cache:
            current_sig = self._stat_sig_cache[stat_path]
        else:
            try:
                st = os.stat(stat_path)
                current_sig = [st.st_mtime_ns, st.st_ino]
            except OSError:
                current_sig = None
            self._stat_sig_cache[stat_path] = current_sig

        if current_sig is not None and current_sig == sig:
            if cur != path:
                self.entries[path] = entry
            return True, entry.get("repo")

        # Invalidate: .git was moved, deleted, or changed
        return False, None

    def put(self, path: str, repo: Optional[dict], dotgit: Optional[str] = None,
            sig: Optional[list] = None, now: Optional[float] = None) -> None:
        if repo is None:
            current_time = time.time() if now is None else now
            self.entries[path] = {"repo": None, "ts": current_time}
            self.dirty = True
        else:
            if dotgit and sig:
                self.entries[path] = {
                    "repo": repo,
                    "dotgit": dotgit,
                    "sig": sig,
                }
                self.dirty = True

    def save(self) -> None:
        if not self.dirty:
            return
        tmp = None
        try:
            os.makedirs(self.dir, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".repo-cache-", dir=self.dir)
            data = json.dumps({"version": REPO_CACHE_VERSION, "paths": self.entries},
                              ensure_ascii=False, separators=(",", ":"))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
            del data
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError:
            pass
        finally:
            if tmp is not None and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass


class SessionCache:
    def __init__(self, directory: Optional[str] = None):
        self.dir = directory or _cache_dir()
        self.path = os.path.join(self.dir, "parse-cache-v%d.json" % CACHE_VERSION)
        self.journal_path = os.path.join(self.dir, "parse-cache-v%d.journal.jsonl" % CACHE_VERSION)
        self.repo_cache = RepoCache(self.dir)
        self.entries: Dict[str, dict] = {}
        self.used = set()
        self.modified_keys: Set[str] = set()
        self.dirty = False
        self.dirty_keys: Set[str] = set()
        self._session_cache: Dict[str, Session] = {}
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and data.get("version") == CACHE_VERSION:
                self.entries = data.get("files") or {}
        except (OSError, ValueError):
            self.entries = {}
        if os.path.isfile(self.journal_path):
            try:
                with open(self.journal_path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        line = line.strip()
                        if not line:
                            continue
                        row = json.loads(line)
                        k = row.get("k")
                        if not k:
                            continue
                        if row.get("d"):
                            self.entries.pop(k, None)
                        elif "v" in row:
                            self.entries[k] = row["v"]
            except (OSError, ValueError):
                pass

    def get(self, agent: str, path: str, parent: Optional[str], parse: Callable) -> Session:
        key = "%s\0%s\0%s" % (agent, path, parent or "")
        self.used.add(key)
        sig = _signature(path)
        entry = self.entries.get(key)
        if entry is not None and sig is not None and entry.get("sig") == sig:
            if "error" in entry:
                raise ParseError(entry["error"])
            if key in self._session_cache:
                return self._session_cache[key]
            try:
                s = _load_session(entry["session"])
                self._session_cache[key] = s
                return s
            except (TypeError, KeyError, ValueError):
                pass
        try:
            session = parse(path, parent)
        except ParseError as exc:
            self.modified_keys.add(path)
            if sig is not None:
                self.entries[key] = {"sig": sig, "error": str(exc)}
                self.dirty = True
                self.dirty_keys.add(key)
            raise
        if sig is not None:
            dumped = _dump_session(session)
            if entry is not None and entry.get("session") == dumped:
                entry["sig"] = sig
                return session
            self.modified_keys.add(path)
            self.entries[key] = {"sig": sig, "session": dumped}
            self.dirty = True
            self.dirty_keys.add(key)
        else:
            self.modified_keys.add(path)
        return session

    def save(self) -> None:
        try:
            current_name = os.path.basename(self.path)
            for fname in os.listdir(self.dir):
                if (fname.startswith("parse-cache-v")
                        and fname.endswith(".json")
                        and fname != current_name):
                    try:
                        os.unlink(os.path.join(self.dir, fname))
                    except OSError:
                        pass
        except OSError:
            pass

        stale = set(self.entries) - self.used
        for key in stale:
            del self.entries[key]
        if not (self.dirty or stale):
            self.repo_cache.save()
            return

        # Proportional save: append to journal if under threshold and parse-cache exists
        if os.path.isfile(self.path) and not stale and self.dirty_keys and len(self.dirty_keys) <= 500:
            try:
                j_size = os.path.getsize(self.journal_path) if os.path.isfile(self.journal_path) else 0
                if j_size < 5 * 1024 * 1024:
                    with open(self.journal_path, "a", encoding="utf-8") as handle:
                        for key in sorted(self.dirty_keys):
                            if key in self.entries:
                                handle.write(json.dumps({"k": key, "v": self.entries[key]}, ensure_ascii=False) + "\n")
                    self.dirty = False
                    self.dirty_keys.clear()
                    self.repo_cache.save()
                    return
            except OSError:
                pass

        tmp = None
        try:
            os.makedirs(self.dir, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".parse-cache-", dir=self.dir)
            data = json.dumps({"version": CACHE_VERSION, "files": self.entries},
                              ensure_ascii=False, separators=(",", ":"))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
            del data
            os.replace(tmp, self.path)
            try:
                if os.path.isfile(self.journal_path):
                    os.unlink(self.journal_path)
            except OSError:
                pass
            self.dirty = False
            self.dirty_keys.clear()
        except OSError:
            pass  # a cache that cannot be written only costs speed
        finally:
            if tmp is not None and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        self.repo_cache.save()
