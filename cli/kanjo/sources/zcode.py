"""ZCode coding agent: ``~/.zcode/cli/db/db.sqlite`` (SQLite).

Reads session metadata from the ``session`` table and model usage from the ``model_usage`` table.
Each session record carries directory (cwd), title, created/updated timestamps, and parent session link.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any, Dict, List, Optional, Set, Tuple

from .. import winsupport
from .base import (
    Message,
    ParseError,
    Session,
    clean_title,
    env_dirs,
    open_sqlite_ro,
    unique,
    split_path_list,
)

AGENT = "zcode"


def roots() -> List[str]:
    explicit = (
        os.environ.get("KANJO_ZCODE_DIR")
        or os.environ.get("TOKEI_ZCODE_DB")
        or os.environ.get("KANJO_ZCODE_DB")
    )
    if explicit:
        return [winsupport.abspath(winsupport.expanduser(p)) for p in split_path_list(explicit) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    candidates = [
        winsupport.expanduser("~/.zcode/cli/db"),
        winsupport.expanduser("~/.zcode"),
    ]
    existing = [winsupport.abspath(c) for c in candidates if os.path.exists(c)]
    return existing[:1] if existing else [winsupport.abspath(candidates[0])]


def _db_path(root: str) -> Optional[str]:
    if os.path.isfile(root) and (root.endswith(".db") or root.endswith(".sqlite")):
        return root
    for name in ("db.sqlite", "sqlite.db", "cli/db/db.sqlite"):
        cand = os.path.join(root, name)
        if os.path.isfile(cand):
            return cand
    return None


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(db_path::session_id, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    for root in dirs if dirs is not None else roots():
        db = _db_path(root)
        if not db:
            continue
        try:
            with open_sqlite_ro(db) as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, parent_id FROM session ORDER BY time_created ASC")
                for sid, parent in cur:
                    if sid:
                        key = f"{db}::{sid}"
                        if key not in seen:
                            seen.add(key)
                            found.append((key, parent or None))
        except (ParseError, sqlite3.Error):
            continue
    return found


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if "::" in path:
        db_path, sid = path.split("::", 1)
    else:
        db_path, sid = path, None

    if not os.path.isfile(db_path):
        raise ParseError(f"ZCode database not found: {db_path}")

    with open_sqlite_ro(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        try:
            if sid:
                cur.execute(
                    "SELECT id, parent_id, directory, path, title, time_created, time_updated FROM session WHERE id = ?",
                    (sid,),
                )
                session_row = cur.fetchone()
            else:
                cur.execute(
                    "SELECT id, parent_id, directory, path, title, time_created, time_updated FROM session ORDER BY time_created ASC LIMIT 1"
                )
                session_row = cur.fetchone()
        except sqlite3.Error as exc:
            raise ParseError(f"failed to query session from {db_path}: {exc}")

        if not session_row:
            raise ParseError(f"session {sid} not found in {db_path}")

        session_id = session_row["id"]
        parent_id = subagent_of or session_row["parent_id"]
        session = Session(id=session_id, agent=AGENT, file=path, subagent_of=parent_id)

        title = session_row["title"]
        if title:
            session.title = clean_title(title)

        directory = session_row["directory"] or session_row["path"]
        if directory:
            session.note_cwd(winsupport.abspath(directory))

        time_created = session_row["time_created"]
        if time_created:
            c_ts = float(time_created) / 1000.0 if float(time_created) > 100_000_000_000 else float(time_created)
            session.origin_ts = c_ts
            session.note_time(c_ts)

        # Query model usage
        try:
            cur.execute(
                """
                SELECT id, model_id, input_tokens, output_tokens, reasoning_tokens,
                       cache_creation_input_tokens, cache_read_input_tokens,
                       started_at, completed_at
                FROM model_usage
                WHERE session_id = ?
                ORDER BY started_at ASC
                """,
                (session_id,),
            )
            usage_rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise ParseError(f"failed to query model_usage from {db_path}: {exc}")

        for r in usage_rows:
            raw_ts = r["completed_at"] or r["started_at"]
            ts = float(raw_ts) / 1000.0 if raw_ts and float(raw_ts) > 100_000_000_000 else (float(raw_ts) if raw_ts else None)
            if ts:
                session.note_time(ts)

            inp_tot = int(r["input_tokens"] or 0)
            out_tot = int(r["output_tokens"] or 0)
            reasoning = int(r["reasoning_tokens"] or 0)
            cw = int(r["cache_creation_input_tokens"] or 0)
            cr = int(r["cache_read_input_tokens"] or 0)

            inp = max(0, inp_tot - cr - cw)
            thinking = min(reasoning, out_tot) if out_tot else reasoning
            row_id = r["id"]

            session.messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model=str(r["model_id"] or "GLM-5.2"),
                    input=inp,
                    output=out_tot,
                    cache_read=cr,
                    cache_write=cw,
                    thinking=thinking,
                    cwd=session.cwd,
                    key=f"{AGENT}:{session.id}:{row_id}",
                )
            )

    if parent_id:
        session.id = f"{parent_id}/{session.id}"
    return session
