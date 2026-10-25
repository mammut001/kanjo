"""Permanent session ledger.

The parse cache forgets a file when the log disappears. The ledger does not:
deleting logs must not delete token history. The file is
``$KANJO_DATA_DIR/ledger.json`` or ``~/.local/share/kanjo/ledger.json``.

One entry per ``agent + session id + parent``. The value is the same serialized
session the cache stores, plus ``source_path`` (the first path, kept for older
readers), ``source_paths`` (every file that contributed, sorted and unique),
``imported_at`` and ``file_sig`` (the cache signature of ``source_path``).
Entries loaded without ``source_paths`` get ``[source_path]``. An entry is
rewritten only when a contributing file's signature is new or its path was not
recorded yet. On upsert the path lists are unioned.

A discovered file that produces no billable messages, or that raises
``ParseError``, is stored as a lightweight row (``empty`` or ``error``) keyed
by path. Those rows count as imported and are never turned back into sessions.
Session entries are never dropped because the file is gone; ``--forget-orphans``
is the only removal. A session is an orphan only when every recorded path is gone.
"""

from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional, Tuple, Union

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


def marker_key(agent: str, source_path: str) -> str:
    """Key for an empty or unreadable file. One separator, so it cannot collide
    with ``entry_key`` (which always contains two)."""
    return "%s\0%s" % (agent, source_path)


def agent_of(key: object, entry: dict) -> Optional[str]:
    session = entry.get("session") if isinstance(entry, dict) else None
    if isinstance(session, dict):
        agent = session.get("agent")
        if isinstance(agent, str) and agent:
            return agent
    if isinstance(key, str) and "\0" in key:
        head = key.split("\0", 1)[0]
        if head:
            return head
    return None


def paths_of(entry: dict) -> List[str]:
    """Sorted unique source paths. Missing ``source_paths`` falls back to ``source_path``."""
    if not isinstance(entry, dict):
        return []
    found: List[str] = []
    seen = set()
    raw = entry.get("source_paths")
    if isinstance(raw, list):
        for path in raw:
            if isinstance(path, str) and path and path not in seen:
                seen.add(path)
                found.append(path)
    if not found:
        path = entry.get("source_path")
        if isinstance(path, str) and path:
            found.append(path)
    found.sort()
    return found


def _is_session_entry(entry: dict) -> bool:
    return isinstance(entry, dict) and isinstance(entry.get("session"), dict)


def _known_sigs(entry: dict) -> dict:
    """Path -> signature last stored for that path."""
    sigs = {}
    if not isinstance(entry, dict):
        return sigs
    raw = entry.get("path_sigs")
    if isinstance(raw, dict):
        for path, sig in raw.items():
            if isinstance(path, str) and path:
                sigs[path] = sig
    primary = entry.get("source_path")
    if isinstance(primary, str) and primary and primary not in sigs and "file_sig" in entry:
        sigs[primary] = entry.get("file_sig")
    elif "file_sig" in entry:
        paths = paths_of(entry)
        if len(paths) == 1 and paths[0] not in sigs:
            sigs[paths[0]] = entry.get("file_sig")
    return sigs


def _migrate_entry(entry: dict) -> None:
    """In-memory only: old rows gain ``source_paths`` without rewriting the file."""
    if isinstance(entry, dict):
        entry["source_paths"] = paths_of(entry)


def _all_missing(entry: dict) -> bool:
    paths = paths_of(entry)
    if not paths:
        return True
    return all(not os.path.exists(path) for path in paths)


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
            for entry in entries.values():
                _migrate_entry(entry)
            self.entries = entries
        updated = data.get("updated_at")
        if isinstance(updated, str):
            self.updated_at = updated

    def note_file(self, session: Session, source_paths: Union[str, List[str]]) -> None:
        """Upsert ``session``, unioning ``source_paths`` with any already stored.

        ``source_paths`` is one path or a list. No-op when every path is already
        recorded and its signature is unchanged. ``source_path`` stays the first
        sorted path so older readers still see a single file.
        """
        incoming = [source_paths] if isinstance(source_paths, str) else list(source_paths or [])
        deduped: List[str] = []
        for path in incoming:
            if isinstance(path, str) and path and path not in deduped:
                deduped.append(path)
        if not deduped:
            return
        for path in deduped:
            self._drop_marker(session.agent, path)
        sigs_now = {path: _signature(path) for path in deduped}
        key = entry_key(session.agent, session.id, session.subagent_of)
        old = self.entries.get(key)
        old_is_session = _is_session_entry(old)
        old_paths = paths_of(old) if old_is_session else []
        new_paths = sorted(set(old_paths) | set(deduped))
        old_sigs = _known_sigs(old) if old_is_session else {}
        if (old_is_session and set(deduped) <= set(old_paths)
                and all(old_sigs.get(path) == sigs_now[path] for path in deduped)):
            return
        known = dict(old_sigs)
        known.update(sigs_now)
        primary = new_paths[0]
        file_sig = known.get(primary)
        if file_sig is None:
            file_sig = _signature(primary)
        entry = {
            "session": _dump_session(session),
            "source_path": primary,
            "source_paths": new_paths,
            "imported_at": iso_utc(time.time()),
            "file_sig": file_sig,
        }
        if len(new_paths) > 1:
            entry["path_sigs"] = {path: known[path] for path in new_paths if path in known}
        self.entries[key] = entry
        self.dirty = True

    def note_unparsed(self, agent: str, source_path: str, error: Optional[str] = None) -> None:
        """Record a discovered file that did not become a session.

        ``error`` is the parse failure text. Without it the file had no billable
        messages and any session row that listed this path loses it, so the file
        is not exported as a session later.
        """
        if error is None:
            self._detach_path(agent, source_path)
        sig = _signature(source_path)
        key = marker_key(agent, source_path)
        paths = [source_path]
        old = self.entries.get(key)
        same_file = (isinstance(old, dict) and old.get("source_paths") == paths
                     and old.get("file_sig") == sig and "session" not in old)
        if same_file and error is None and old.get("empty") is True and "error" not in old:
            return
        if same_file and error is not None and old.get("error") == error:
            return
        entry = {
            "source_paths": paths,
            "file_sig": sig,
            "imported_at": iso_utc(time.time()),
        }
        if error is None:
            entry["empty"] = True
        else:
            entry["error"] = error
        self.entries[key] = entry
        self.dirty = True

    def _drop_marker(self, agent: str, source_path: str) -> None:
        key = marker_key(agent, source_path)
        if key in self.entries:
            del self.entries[key]
            self.dirty = True

    def _detach_path(self, agent: str, source_path: str) -> None:
        """Remove ``source_path`` from session rows. Drop a row whose last path it was."""
        for key, entry in list(self.entries.items()):
            if not _is_session_entry(entry) or agent_of(key, entry) != agent:
                continue
            current = paths_of(entry)
            if source_path not in current:
                continue
            remaining = [path for path in current if path != source_path]
            if not remaining:
                del self.entries[key]
                self.dirty = True
                continue
            sigs = _known_sigs(entry)
            sigs.pop(source_path, None)
            entry["source_paths"] = remaining
            entry["source_path"] = remaining[0]
            if len(remaining) > 1:
                entry["path_sigs"] = {path: sigs[path] for path in remaining if path in sigs}
            else:
                entry.pop("path_sigs", None)
            if remaining[0] in sigs:
                entry["file_sig"] = sigs[remaining[0]]
            self.dirty = True

    def orphan_sessions(self) -> List[Tuple[str, Session]]:
        """Session entries whose log files are all gone, as ``(key, session)``.

        Empty and error rows are not sessions. A row that still has one file on
        disk is skipped; the scan reads that file.
        """
        found = []
        for key, entry in self.entries.items():
            if not _is_session_entry(entry) or not _all_missing(entry):
                continue
            try:
                found.append((key, _load_session(dict(entry["session"]))))
            except (TypeError, KeyError, ValueError):
                continue
        return found

    def signatures_by_path(self) -> Dict[str, list]:
        found: Dict[str, list] = {}
        for entry in self.entries.values():
            if not isinstance(entry, dict):
                continue
            sigs = _known_sigs(entry)
            for path in paths_of(entry):
                found.setdefault(path, []).append(sigs.get(path, entry.get("file_sig")))
        return found

    def summary(self) -> dict:
        sessions = orphaned = empty = errors = 0
        for entry in self.entries.values():
            if isinstance(entry, dict) and entry.get("empty") is True and not _is_session_entry(entry):
                empty += 1
                continue
            if isinstance(entry, dict) and "error" in entry and not _is_session_entry(entry):
                errors += 1
                continue
            sessions += 1
            if _all_missing(entry):
                orphaned += 1
        return {
            "path": self.path,
            "sessions": sessions,
            "orphaned": orphaned,
            "empty": empty,
            "errors": errors,
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
            if _is_session_entry(entry) and _all_missing(entry):
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
