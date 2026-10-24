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
from dataclasses import asdict
from typing import Callable, Dict, Optional

from .sources.base import Message, ParseError, Session

CACHE_VERSION = 3
_MSG_FIELDS = ("ts", "model", "input", "output", "cache_read", "cache_write", "cache_write_1h",
               "thinking", "cwd", "branch", "key")


def _cache_dir() -> str:
    explicit = os.environ.get("KANJO_CACHE_DIR")
    if explicit:
        return os.path.expanduser(explicit)
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "kanjo")


def _signature(path: str) -> Optional[list]:
    sig = []
    for p in (path, path + "-wal"):
        try:
            st = os.stat(p)
        except OSError:
            if p == path:
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


class SessionCache:
    def __init__(self, directory: Optional[str] = None):
        self.dir = directory or _cache_dir()
        self.path = os.path.join(self.dir, "parse-cache-v%d.json" % CACHE_VERSION)
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
        if not (self.dirty or stale):
            return
        try:
            os.makedirs(self.dir, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".parse-cache-", dir=self.dir)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"version": CACHE_VERSION, "files": self.entries}, handle,
                          ensure_ascii=False, separators=(",", ":"))
            os.replace(tmp, self.path)
        except OSError:
            pass  # a cache that cannot be written only costs speed
