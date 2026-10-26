"""OpenCode: ``~/.local/share/opencode/opencode.db`` (SQLite).

Parses sessions and messages recorded by OpenCode.
MiniMax agent sessions that run inside OpenCode are filtered out to avoid double-counting.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import List, Optional, Set, Tuple

from .base import (
    Message,
    ParseError,
    Session,
    absolutize,
    env_dirs,
    extract_paths,
    git_branch,
    open_sqlite_ro,
    paths_from_args,
    short_title,
)

AGENT = "opencode"
PATH_KEYS = {"file_path", "path", "filepath", "directory", "dir", "cwd", "workdir", "target_file", "file"}
CMD_KEYS = {"command", "cmd"}


def roots() -> List[str]:
    return env_dirs("KANJO_OPENCODE_DIR", ["~/.local/share/opencode"])


def _db_path(root: str) -> Optional[str]:
    if os.path.isfile(root) and (root.endswith(".db") or root.endswith(".sqlite")):
        return root
    candidate = os.path.join(root, "opencode.db")
    if os.path.isfile(candidate):
        return candidate
    return None


def _minimax_session_ids() -> Optional[Set[str]]:
    """Framework session ids recorded by MiniMax that OpenCode must exclude.

    Returns None if a MiniMax database file exists but cannot be read, signalling
    that the OpenCode scan should be skipped to prevent double-counting.
    """
    sids: Set[str] = set()
    mm_dirs = env_dirs("KANJO_MINIMAX_DIR", ["~/.minimax"])
    for root in mm_dirs:
        db = os.path.join(root, "sqlite.db") if os.path.isdir(root) else root
        if os.path.isfile(db):
            try:
                with open_sqlite_ro(db) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT framework_session_id FROM sessions WHERE framework_session_id IS NOT NULL")
                    for (fid,) in cur.fetchall():
                        if fid:
                            sids.add(fid)
            except (ParseError, sqlite3.Error, OSError) as exc:
                print("warning: MiniMax db %s exists but cannot be read: %s; skipping OpenCode scan" % (db, exc), file=sys.stderr)
                return None
    return sids


def _is_minimax_session(directory: Optional[str], session_id: str, mm_ids: Set[str]) -> bool:
    if session_id in mm_ids:
        return True
    if not directory:
        return False
    norm = directory.lower()
    return "/.minimax/" in norm or "/.mavis/" in norm or norm.endswith("/.minimax") or norm.endswith("/.mavis")


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(path_with_session_id, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    mm_ids = _minimax_session_ids()
    if mm_ids is None:
        return []
    for root in dirs if dirs is not None else roots():
        db = _db_path(root)
        if not db:
            continue
        try:
            with open_sqlite_ro(db) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute("SELECT id, parent_id, directory FROM session ORDER BY time_created")
                for row in cur.fetchall():
                    sid = row["id"]
                    directory = row["directory"]
                    parent = row["parent_id"]
                    if _is_minimax_session(directory, sid, mm_ids):
                        continue
                    found.append((f"{db}::{sid}", parent or None))
        except (ParseError, sqlite3.Error):
            continue
    return found


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if "::" in path:
        db_path, sid = path.split("::", 1)
    else:
        db_path, sid = path, None

    if not os.path.isfile(db_path):
        raise ParseError("OpenCode database not found: %s" % db_path)

    mm_ids = _minimax_session_ids()
    if mm_ids is None:
        raise ParseError("MiniMax database exists but cannot be read; skipping OpenCode scan")

    with open_sqlite_ro(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        try:
            if sid:
                cur.execute(
                    "SELECT id, project_id, parent_id, directory, title, time_created, time_updated FROM session WHERE id = ?",
                    (sid,),
                )
                session_row = cur.fetchone()
            else:
                cur.execute("SELECT id, project_id, parent_id, directory, title, time_created, time_updated FROM session ORDER BY time_created LIMIT 1")
                session_row = cur.fetchone()
        except sqlite3.Error as exc:
            raise ParseError("failed to query session from %s: %s" % (db_path, exc))

        if not session_row:
            raise ParseError("session %s not found in %s" % (sid, db_path))

        sid = session_row["id"]
        directory = session_row["directory"]
        if _is_minimax_session(directory, sid, mm_ids):
            raise ParseError("session %s belongs to MiniMax, excluded from OpenCode" % sid)

        project_id = session_row["project_id"]
        parent_id = session_row["parent_id"]
        title = session_row["title"]
        time_created = session_row["time_created"]

        worktree = None
        if project_id:
            try:
                cur.execute("SELECT worktree FROM project WHERE id = ?", (project_id,))
                prow = cur.fetchone()
                if prow and prow["worktree"]:
                    worktree = prow["worktree"]
            except sqlite3.Error:
                pass

        cwd = directory or worktree
        effective_parent = subagent_of or parent_id or None
        session = Session(id=sid, agent=AGENT, file=path, subagent_of=effective_parent)
        session.note_cwd(cwd)
        session.branch = git_branch(cwd)
        session.title = short_title(title)
        if time_created:
            session.origin_ts = time_created / 1000.0
            session.note_time(session.origin_ts)

        # Query messages
        try:
            cur.execute("SELECT id, time_created, data FROM message WHERE session_id = ? ORDER BY time_created, id", (sid,))
            msg_rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise ParseError("failed to query messages for session %s: %s" % (sid, exc))

        user_title_candidate = None
        for mrow in msg_rows:
            raw_data = mrow["data"]
            if not raw_data:
                continue
            try:
                data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            except (ValueError, TypeError):
                continue
            if not isinstance(data, dict):
                continue

            role = data.get("role")
            if role == "user" and not user_title_candidate:
                content = data.get("content")
                if isinstance(content, str) and content.strip():
                    user_title_candidate = short_title(content)

            if role == "assistant":
                tokens = data.get("tokens") or {}
                inp = int(tokens.get("input") or 0)
                out = int(tokens.get("output") or 0)
                reasoning = int(tokens.get("reasoning") or 0)
                cache = tokens.get("cache") or {}
                cache_read = int(cache.get("read") or 0)
                cache_write = int(cache.get("write") or 0)

                model = data.get("modelID") or data.get("model") or "unknown"
                ts = (mrow["time_created"] / 1000.0) if mrow["time_created"] else None
                mid = mrow["id"]
                key = f"opencode:{mid}"

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

        if (not session.title or session.title.startswith("New session")) and user_title_candidate:
            session.title = user_title_candidate

        # Query tool calls from part table
        try:
            cur.execute(
                "SELECT data FROM part WHERE session_id = ? AND json_extract(data, '$.type') = 'tool' ORDER BY time_created",
                (sid,),
            )
            for prow in cur.fetchall():
                raw_part = prow["data"]
                if not raw_part:
                    continue
                try:
                    pdata = json.loads(raw_part) if isinstance(raw_part, str) else raw_part
                except (ValueError, TypeError):
                    continue
                if not isinstance(pdata, dict):
                    continue
                state = pdata.get("state")
                if not isinstance(state, dict):
                    continue
                t_input = state.get("input")
                call_paths: List[str] = []
                if isinstance(t_input, dict):
                    call_paths.extend(paths_from_args(t_input, cwd, PATH_KEYS, CMD_KEYS))
                elif isinstance(t_input, str):
                    call_paths.extend(extract_paths(t_input))
                if call_paths:
                    session.tool_paths.append(call_paths)
        except sqlite3.Error:
            pass

    return session
