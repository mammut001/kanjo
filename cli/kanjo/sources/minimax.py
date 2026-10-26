"""MiniMax: ``~/.minimax/sqlite.db`` (SQLite).

Reads token usage and sessions from the local MiniMax Mavis agent database.
Handles SQLite WAL and concurrency safely by copying to temp in read-only mode.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import List, Optional, Set, Tuple

from .base import (
    Message,
    ParseError,
    Session,
    absolutize,
    env_dirs,
    git_branch,
    open_sqlite_ro,
    short_title,
)

AGENT = "minimax"


def roots() -> List[str]:
    return env_dirs("KANJO_MINIMAX_DIR", ["~/.minimax"])


def _db_path(root: str) -> Optional[str]:
    if os.path.isfile(root) and (root.endswith(".db") or root.endswith(".sqlite")):
        return root
    candidate = os.path.join(root, "sqlite.db")
    if os.path.isfile(candidate):
        return candidate
    return None


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(path_with_session_id, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    for root in dirs if dirs is not None else roots():
        db = _db_path(root)
        if not db:
            continue
        try:
            with open_sqlite_ro(db) as conn:
                cur = conn.cursor()
                try:
                    cur.execute("""
                        SELECT s.session_id, p.parent_session_id
                        FROM sessions s
                        LEFT JOIN session_peers p ON s.session_id = p.session_id
                        ORDER BY s.created_at
                    """)
                    for sid, parent in cur.fetchall():
                        found.append((f"{db}::{sid}", parent or None))
                except sqlite3.Error:
                    # Fallback if session_peers does not exist
                    cur.execute("SELECT session_id FROM sessions ORDER BY created_at")
                    for (sid,) in cur.fetchall():
                        found.append((f"{db}::{sid}", None))
        except (ParseError, sqlite3.Error):
            continue
    return found


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if "::" in path:
        db_path, sid = path.split("::", 1)
    else:
        db_path, sid = path, None

    if not os.path.isfile(db_path):
        raise ParseError("MiniMax database not found: %s" % db_path)

    with open_sqlite_ro(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        try:
            if sid:
                cur.execute(
                    "SELECT session_id, agent_name, title, workspace_dir, created_at FROM sessions WHERE session_id = ?",
                    (sid,),
                )
                session_row = cur.fetchone()
            else:
                cur.execute("SELECT session_id, agent_name, title, workspace_dir, created_at FROM sessions ORDER BY created_at LIMIT 1")
                session_row = cur.fetchone()
        except sqlite3.Error as exc:
            raise ParseError("failed to query sessions from %s: %s" % (db_path, exc))

        if not session_row:
            raise ParseError("session %s not found in %s" % (sid, db_path))

        sid = session_row["session_id"]
        session = Session(id=sid, agent=AGENT, file=path, subagent_of=subagent_of)

        cwd = session_row["workspace_dir"]
        title = session_row["title"]
        created_at = session_row["created_at"]

        # If workspace_dir is empty in sessions table, try journal
        if not cwd:
            try:
                cur.execute(
                    "SELECT workspace_dir FROM session_turn_file_change_journal WHERE session_id = ? AND workspace_dir IS NOT NULL LIMIT 1",
                    (sid,),
                )
                jrow = cur.fetchone()
                if jrow and jrow["workspace_dir"]:
                    cwd = jrow["workspace_dir"]
            except sqlite3.Error:
                pass

        session.note_cwd(cwd)
        session.branch = git_branch(cwd)
        session.title = short_title(title)
        if created_at:
            session.origin_ts = created_at / 1000.0
            session.note_time(session.origin_ts)

        # Query token usage
        try:
            cur.execute(
                """
                SELECT id, turn_id, model, ts, input_tokens, output_tokens,
                       reasoning_tokens, cache_read_tokens, cache_write_tokens
                FROM token_usage
                WHERE session_id = ?
                ORDER BY ts, id
                """,
                (sid,),
            )
            usage_rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise ParseError("failed to query token_usage for session %s: %s" % (sid, exc))

        seen_turn_ids: Set[str] = set()
        for row in usage_rows:
            ts = (row["ts"] / 1000.0) if row["ts"] else None
            model = row["model"] or "unknown"
            inp = int(row["input_tokens"] or 0)
            out = int(row["output_tokens"] or 0)
            reasoning = int(row["reasoning_tokens"] or 0)
            cache_read = int(row["cache_read_tokens"] or 0)
            cache_write = int(row["cache_write_tokens"] or 0)
            turn_id = row["turn_id"] or str(row["id"])
            row_id = row["id"]
            if turn_id in seen_turn_ids:
                key = f"minimax:{sid}:{turn_id}:{row_id}"
            else:
                key = f"minimax:{sid}:{turn_id}"
                seen_turn_ids.add(turn_id)

            session.note_time(ts)
            session.messages.append(
                Message(
                    ts=ts or 0.0,
                    model=model,
                    input=inp,
                    output=out,
                    cache_read=cache_read,
                    cache_write=cache_write,
                    thinking=reasoning,
                    cwd=session.cwd,
                    branch=session.branch,
                    key=key,
                )
            )

        # Query tool file changes for attribution
        try:
            cur.execute(
                "SELECT workspace_dir, paths_json FROM session_turn_file_change_journal WHERE session_id = ? ORDER BY created_at",
                (sid,),
            )
            for jrow in cur.fetchall():
                pj = jrow["paths_json"]
                jws = jrow["workspace_dir"] or cwd
                if not pj:
                    continue
                try:
                    paths = json.loads(pj) if isinstance(pj, str) else pj
                    if isinstance(paths, list):
                        call_paths = []
                        for p in paths:
                            abs_p = absolutize(p, jws)
                            if abs_p:
                                call_paths.append(abs_p)
                        if call_paths:
                            session.tool_paths.append(call_paths)
                except (ValueError, TypeError):
                    pass
        except sqlite3.Error:
            pass

    return session
