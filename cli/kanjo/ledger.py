"""Permanent session ledger.

The parse cache forgets a file when the log disappears. The ledger does not:
deleting logs must not delete token history. The file is
``$KANJO_DATA_DIR/ledger.json`` or ``~/.local/share/kanjo/ledger.json``.

One entry per ``agent + session id + parent``. The value is the same serialized
session the cache stores, plus ``source_path``, ``imported_at`` and ``file_sig``
(the cache signature at import). An entry is rewritten only when that signature
or the source path changes. Entries are never dropped because the file is gone;
``--forget-orphans`` is the only removal.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Tuple

from .cache import _dump_session, _load_session, _signature
from .sources.base import Session, iso_utc

LEDGER_VERSION = 1
_EMPTY_UPDATED_AT = "1970-01-01T00:00:00Z"


def data_dir() -> str:
    explicit = os.environ.get("KANJO_DATA_DIR")
    if explicit:
        return os.path.expanduser(explicit)
    return os.path.join(os.path.expanduser("~"), ".local", "share", "kanjo")


def entry_key(agent: str, session_id: str, parent: Optional[str]) -> str:
    return "%s\0%s\0%s" % (agent, session_id, parent or "")


class Ledger:
    """Loaded once per process run. Callers mutate it in memory and ``save`` once."""

    def __init__(self, directory: Optional[str] = None):
        self.dir = directory or data_dir()
        self.path = os.path.join(self.dir, "ledger.json")
        self.entries: Dict[str, dict] = {}
        self.updated_at: Optional[str] = None
        self.dirty = False
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict) or data.get("version") != LEDGER_VERSION:
            return
        entries = data.get("entries")
        if isinstance(entries, dict):
            self.entries = entries
        updated = data.get("updated_at")
        if isinstance(updated, str):
            self.updated_at = updated

    def note_file(self, session: Session, source_path: str) -> None:
        """Upsert the parsed session. No-op when the signature and path are unchanged."""
        sig = _signature(source_path)
        key = entry_key(session.agent, session.id, session.subagent_of)
        old = self.entries.get(key)
        if old is not None and old.get("file_sig") == sig and old.get("source_path") == source_path:
            return
        self.entries[key] = {
            "session": _dump_session(session),
            "source_path": source_path,
            "imported_at": iso_utc(time.time()),
            "file_sig": sig,
        }
        self.dirty = True

    def orphan_sessions(self) -> List[Tuple[str, Session]]:
        """Ledger entries whose log file is gone, as ``(key, session)``."""
        found = []
        for key, entry in self.entries.items():
            path = entry.get("source_path") or ""
            if path and os.path.exists(path):
                continue
            raw = entry.get("session")
            if not isinstance(raw, dict):
                continue
            try:
                found.append((key, _load_session(dict(raw))))
            except (TypeError, KeyError, ValueError):
                continue
        return found

    def signatures_by_path(self) -> Dict[str, list]:
        found: Dict[str, list] = {}
        for entry in self.entries.values():
            path = entry.get("source_path")
            if path:
                found.setdefault(path, []).append(entry.get("file_sig"))
        return found

    def summary(self) -> dict:
        orphaned = 0
        for entry in self.entries.values():
            path = entry.get("source_path") or ""
            if not path or not os.path.exists(path):
                orphaned += 1
        return {
            "path": self.path,
            "sessions": len(self.entries),
            "orphaned": orphaned,
            "updated_at": self.updated_at or _EMPTY_UPDATED_AT,
        }

    def size_bytes(self) -> int:
        try:
            return os.path.getsize(self.path)
        except OSError:
            return 0

    def forget_orphans(self) -> int:
        gone = []
        for key, entry in self.entries.items():
            path = entry.get("source_path") or ""
            if not path or not os.path.exists(path):
                gone.append(key)
        for key in gone:
            del self.entries[key]
        if gone:
            self.dirty = True
            self.save()
        return len(gone)

    def save(self) -> None:
        """Atomic replace, same pattern as ``kanjo export -o`` (temp file + rename)."""
        if not self.dirty:
            return
        os.makedirs(self.dir, exist_ok=True)
        stamp = iso_utc(time.time())
        payload = {"version": LEDGER_VERSION, "updated_at": stamp, "entries": self.entries}
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        self.updated_at = stamp
        self.dirty = False
