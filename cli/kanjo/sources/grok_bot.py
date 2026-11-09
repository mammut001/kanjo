"""Grok Bot agent: ``~/Library/Application Support/Grok Bot/sand-client-persistence/*.blob``.

Persists transcript snapshots and session rosters as JSON blobs.
Messages and turns are extracted for activity tracking.
Tokens default to 0 as Grok Bot local persistence records calls without token counts.
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from .base import (
    Message,
    ParseError,
    Session,
    clean_title,
    env_dirs,
    unique,
)

AGENT = "grok_bot"
_MAX_BLOB_BYTES = 64 * 1024 * 1024


def roots() -> List[str]:
    explicit = os.environ.get("KANJO_GROK_BOT_DIR") or os.environ.get("GROK_BOT_DIR")
    if explicit:
        return [os.path.abspath(os.path.expanduser(p)) for p in explicit.split(os.pathsep) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    candidates = [
        os.path.expanduser("~/Library/Application Support/Grok Bot/sand-client-persistence"),
        os.path.expanduser("~/.config/Grok Bot/sand-client-persistence"),
    ]
    existing = [os.path.abspath(c) for c in candidates if os.path.isdir(c)]
    return existing[:1] if existing else [os.path.abspath(candidates[0])]


def _load_blob(path: str) -> Optional[dict]:
    try:
        size = os.path.getsize(path)
        if size <= 0 or size > _MAX_BLOB_BYTES:
            return None
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def _is_transcript_blob(data: dict) -> bool:
    val = data.get("value") if isinstance(data, dict) else None
    if isinstance(val, dict) and "entries" in val and isinstance(val["entries"], list):
        return True
    return False


def _is_roster_blob(data: dict) -> bool:
    val = data.get("value") if isinstance(data, dict) else None
    if isinstance(val, dict) and "rows" in val and isinstance(val["rows"], list):
        return True
    return False


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(transcript_blob_path, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    for root in dirs if dirs is not None else roots():
        if not os.path.isdir(root):
            continue
        for path in sorted(glob.glob(os.path.join(root, "*.blob"))):
            real = os.path.realpath(path)
            if real in seen:
                continue
            data = _load_blob(real)
            if data is not None and _is_transcript_blob(data):
                seen.add(real)
                found.append((path, None))
    return found


def _find_roster_rows(directory: str) -> List[dict]:
    rows: List[dict] = []
    for path in glob.glob(os.path.join(directory, "*.blob")):
        data = _load_blob(path)
        if data is not None and _is_roster_blob(data):
            val = data.get("value") or {}
            for r in val.get("rows", []):
                if isinstance(r, dict):
                    markers = []
                    for c in (r.get("lastMessageId"), r.get("newestEntryId")):
                        if isinstance(c, str) and c:
                            markers.append(c)
                    le = r.get("lastEntry")
                    if isinstance(le, dict):
                        for c in (le.get("id"), le.get("requestId")):
                            if isinstance(c, str) and c:
                                markers.append(c)
                    row_id = r.get("id")
                    if isinstance(row_id, str) and row_id:
                        rows.append({
                            "id": row_id,
                            "path": r.get("path"),
                            "title": r.get("title") or r.get("name"),
                            "markers": set(markers),
                        })
    return rows


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    stem = os.path.splitext(os.path.basename(path))[0]
    data = _load_blob(path)
    if data is None or not _is_transcript_blob(data):
        raise ParseError(f"not a valid Grok Bot transcript blob: {path}")

    val = data.get("value") or {}
    entries = val.get("entries") or []

    # Find roster rows in the same directory to match title, cwd and stable session id
    roster_rows = _find_roster_rows(os.path.dirname(os.path.abspath(path)))
    entry_ids: Set[str] = set()
    first_user_text: Optional[str] = None

    for e in entries:
        if isinstance(e, dict):
            eid = e.get("id")
            if isinstance(eid, str) and eid:
                entry_ids.add(eid)
            if first_user_text is None and e.get("kind") == "message" and e.get("role") == "user":
                content = e.get("content") or e.get("richText") or e.get("text")
                if isinstance(content, str) and content.strip():
                    first_user_text = content.strip()

    matched_row = None
    for r in roster_rows:
        if r["markers"] and entry_ids.intersection(r["markers"]):
            matched_row = r
            break

    sid = stem
    title = None
    cwd = None
    if matched_row:
        sid = matched_row["id"]
        title = clean_title(matched_row.get("title"))
        raw_path = matched_row.get("path")
        if isinstance(raw_path, str) and raw_path.strip():
            cwd = os.path.abspath(os.path.expanduser(raw_path.strip()))
    elif first_user_text:
        title = clean_title(first_user_text)

    session = Session(id=sid, agent=AGENT, file=path, title=title, subagent_of=subagent_of)
    if cwd:
        session.note_cwd(cwd)

    seen_calls: Set[str] = set()
    messages: List[Message] = []

    for idx, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue

        raw_ts = entry.get("timestampMs")
        ts: Optional[float] = None
        if isinstance(raw_ts, (int, float)) and raw_ts > 0:
            ts = float(raw_ts) / 1000.0 if raw_ts > 100_000_000_000 else float(raw_ts)
            session.note_time(ts)
            if session.origin_ts is None:
                session.origin_ts = ts

        kind = entry.get("kind")
        if kind == "send-message":
            req_id = entry.get("requestId") or entry.get("id") or f"call_{idx}"
            call_key = str(req_id)
            if call_key in seen_calls:
                continue
            seen_calls.add(call_key)

            messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model="grok",
                    input=0,
                    output=0,
                    cache_read=0,
                    cache_write=0,
                    cwd=session.cwd,
                    key=f"{AGENT}:{session.id}:{call_key}",
                )
            )

    session.messages = messages
    if subagent_of:
        session.id = f"{subagent_of}/{session.id}"
    return session
