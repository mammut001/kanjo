"""QoderWork desktop agent database: ``~/Library/Application Support/QoderWork/data/agents.db``.

Extracts token usage and sessions from the QoderWork SQLite database.
Only assistant messages with non-empty metadata are counted to avoid duplicating task metrics.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from .base import (
    Message,
    ParseError,
    Session,
    clean_title,
    env_dirs,
    open_sqlite_ro,
)

AGENT = "qoderwork"


def roots() -> List[str]:
    explicit = os.environ.get("KANJO_QODERWORK_DIR") or os.environ.get("TOKEI_QODER_DB")
    if explicit:
        return [os.path.abspath(os.path.expanduser(p)) for p in explicit.split(os.pathsep) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    candidates = [
        os.path.expanduser("~/Library/Application Support/QoderWork/data"),
        os.path.expanduser("~/Library/Application Support/Qoder/data"),
    ]
    existing = [os.path.abspath(c) for c in candidates if os.path.exists(c)]
    return existing[:1] if existing else [os.path.abspath(candidates[0])]


def _db_path(root: str) -> Optional[str]:
    if os.path.isfile(root) and (root.endswith(".db") or root.endswith(".sqlite")):
        return root
    for name in ("agents.db", "local.db", "sqlite.db", "data/agents.db"):
        cand = os.path.join(root, name)
        if os.path.isfile(cand):
            return cand
    return None


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(db_path::chat_id, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    for root in dirs if dirs is not None else roots():
        db = _db_path(root)
        if not db:
            continue
        try:
            with open_sqlite_ro(db) as conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT DISTINCT chat_id FROM messages WHERE metadata != '{}' AND role = 'assistant' ORDER BY created_at"
                )
                for (chat_id,) in cur:
                    if chat_id:
                        key = f"{db}::{chat_id}"
                        if key not in seen:
                            seen.add(key)
                            found.append((key, None))
        except (ParseError, sqlite3.Error):
            continue
    return found


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if "::" in path:
        db_path, chat_id = path.split("::", 1)
    else:
        db_path, chat_id = path, None

    if not os.path.isfile(db_path):
        raise ParseError(f"QoderWork database not found: {db_path}")

    session_id = chat_id or os.path.splitext(os.path.basename(db_path))[0]
    session = Session(id=session_id, agent=AGENT, file=path, subagent_of=subagent_of)

    with open_sqlite_ro(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Query default model from app_settings if available
        default_model = "unknown"
        try:
            cur.execute("SELECT value FROM app_settings WHERE key = 'modelLevel'")
            row = cur.fetchone()
            if row and row["value"]:
                default_model = str(row["value"]).strip('"')
        except sqlite3.Error:
            pass

        # Query session title if sub_chats table exists
        try:
            if chat_id:
                cur.execute("SELECT title FROM sub_chats WHERE chat_id = ? LIMIT 1", (chat_id,))
                t_row = cur.fetchone()
                if t_row and t_row["title"]:
                    session.title = clean_title(t_row["title"])
        except sqlite3.Error:
            pass

        try:
            if chat_id:
                cur.execute(
                    """
                    SELECT id, created_at, metadata
                    FROM messages
                    WHERE chat_id = ? AND metadata != '{}' AND role = 'assistant'
                    ORDER BY created_at ASC
                    """,
                    (chat_id,),
                )
            else:
                cur.execute(
                    """
                    SELECT id, created_at, metadata
                    FROM messages
                    WHERE metadata != '{}' AND role = 'assistant'
                    ORDER BY created_at ASC
                    """
                )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise ParseError(f"failed to query messages from {db_path}: {exc}")

        for row in rows:
            raw_meta = row["metadata"]
            meta = {}
            if isinstance(raw_meta, str):
                try:
                    meta = json.loads(raw_meta)
                except Exception:
                    meta = {}
            elif isinstance(raw_meta, dict):
                meta = raw_meta

            inp = int(meta.get("inputTokens") or 0)
            out = int(meta.get("outputTokens") or 0)
            cr = int(meta.get("cacheReadInputTokens") or meta.get("cachedTokens") or 0)
            cw = int(meta.get("cacheCreationInputTokens") or 0)
            model = str(meta.get("model") or default_model)

            created_at = row["created_at"]
            ts = float(created_at) if created_at else None
            if ts and ts > 100_000_000_000:
                ts /= 1000.0
            if ts:
                session.note_time(ts)
                if session.origin_ts is None:
                    session.origin_ts = ts

            non_cached_in = max(0, inp - cr - cw)
            mid = row["id"]
            session.messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model=model,
                    input=non_cached_in,
                    output=out,
                    cache_read=cr,
                    cache_write=cw,
                    cwd=session.cwd,
                    key=f"{AGENT}:{session.id}:{mid}",
                )
            )

    if subagent_of:
        session.id = f"{subagent_of}/{session.id}"
    return session
