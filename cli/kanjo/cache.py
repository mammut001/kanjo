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
from dataclasses import asdict
from typing import Callable, Dict, List, Optional, Tuple

from .sources.base import Message, ParseError, Session

CACHE_VERSION = 3
REPO_CACHE_VERSION = 1
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
    d = asdict(s)
    d["messages"] = [[getattr(m, f) for f in _MSG_FIELDS] for m in s.messages]
    return d


def _load_session(d: dict) -> Session:
    d = dict(d)
    msgs = d.pop("messages", [])
    s = Session(**d)
    s.messages = [Message(**dict(zip(_MSG_FIELDS, row))) for row in msgs]
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
        try:
            os.makedirs(self.dir, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".repo-cache-", dir=self.dir)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": REPO_CACHE_VERSION, "paths": self.entries}, handle,
                          ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, self.path)
            self.dirty = False
        except OSError:
            pass


class SessionCache:
    def __init__(self, directory: Optional[str] = None):
        self.dir = directory or _cache_dir()
        self.path = os.path.join(self.dir, "parse-cache-v%d.json" % CACHE_VERSION)
        self.repo_cache = RepoCache(self.dir)
        self.entries: Dict[str, dict] = {}
        self.used = set()
        self.dirty = False
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and data.get("version") == CACHE_VERSION:
                self.entries = data.get("files") or {}
        except (OSError, ValueError):
            self.entries = {}

    def get(self, agent: str, path: str, parent: Optional[str], parse: Callable) -> Session:
        key = "%s\0%s\0%s" % (agent, path, parent or "")
        self.used.add(key)
        sig = _signature(path)
        entry = self.entries.get(key)
        if entry is not None and sig is not None and entry.get("sig") == sig:
            if "error" in entry:
                raise ParseError(entry["error"])
            try:
                return _load_session(entry["session"])
            except (TypeError, KeyError, ValueError):
                pass
        try:
            session = parse(path, parent)
        except ParseError as exc:
            if sig is not None:
                self.entries[key] = {"sig": sig, "error": str(exc)}
                self.dirty = True
            raise
        if sig is not None:
            self.entries[key] = {"sig": sig, "session": _dump_session(session)}
            self.dirty = True
        return session

    def save(self) -> None:
        stale = set(self.entries) - self.used
        for key in stale:
            del self.entries[key]
        if self.dirty or stale:
            try:
                os.makedirs(self.dir, exist_ok=True)
                fd, tmp = tempfile.mkstemp(prefix=".parse-cache-", dir=self.dir)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({"version": CACHE_VERSION, "files": self.entries}, handle,
                              ensure_ascii=False, separators=(",", ":"))
                os.replace(tmp, self.path)
                self.dirty = False
            except OSError:
                pass  # a cache that cannot be written only costs speed
        self.repo_cache.save()
