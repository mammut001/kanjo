"""Hermes coding agent: ``~/.hermes/state.db`` (SQLite).

Reads session metadata and model token usage from Hermes' state database.
Supports both legacy sessions-only databases and newer multi-task session_model_usage tables.
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
    split_path_list,
)

AGENT = "hermes"


def roots() -> List[str]:
    explicit = (
        os.environ.get("KANJO_HERMES_DIR")
        or os.environ.get("TOKEI_HERMES_DB")
        or os.environ.get("KANJO_HERMES_DB")
    )
    if explicit:
        return [winsupport.abspath(winsupport.expanduser(p)) for p in split_path_list(explicit) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    candidates = [winsupport.expanduser("~/.hermes")]
    existing = [winsupport.abspath(c) for c in candidates if os.path.exists(c)]
    return existing[:1] if existing else [winsupport.abspath(candidates[0])]


def _db_path(root: str) -> Optional[str]:
    if os.path.isfile(root) and (root.endswith(".db") or root.endswith(".sqlite")):
        return root
    for name in ("state.db", "hermes.db", "db.sqlite"):
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
                tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "sessions" not in tables:
                    continue
                cur.execute("SELECT id FROM sessions WHERE id IS NOT NULL ORDER BY rowid ASC")
                for (sid,) in cur:
                    if sid:
                        key = f"{db}::{sid}"
                        if key not in seen:
                            seen.add(key)
                            found.append((key, None))
        except (ParseError, sqlite3.Error):
            continue
    return found


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if "::" in path:
        db_path, sid = path.split("::", 1)
    else:
        db_path, sid = path, None

    if not os.path.isfile(db_path):
        raise ParseError(f"Hermes database not found: {db_path}")

    with open_sqlite_ro(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "sessions" not in tables:
            raise ParseError(f"sessions table not found in {db_path}")

        session_cols = {row[1] for row in cur.execute("PRAGMA table_info(sessions)")}
        cwd_expr = 's."cwd"' if "cwd" in session_cols else "NULL"
        title_expr = 's."title"' if "title" in session_cols else "NULL"
        model_expr = 's."model"' if "model" in session_cols else "''"
        start_expr = 's."started_at"' if "started_at" in session_cols else "NULL"

        query = f"""
            SELECT s.id, {model_expr} AS model, {start_expr} AS started_at,
                   {cwd_expr} AS cwd, {title_expr} AS title,
                   s.input_tokens, s.output_tokens, s.cache_read_tokens,
                   s.cache_write_tokens, s.reasoning_tokens
            FROM sessions s
        """
        try:
            if sid:
                cur.execute(query + " WHERE s.id = ?", (sid,))
                session_row = cur.fetchone()
            else:
                cur.execute(query + " LIMIT 1")
                session_row = cur.fetchone()
        except sqlite3.Error as exc:
            raise ParseError(f"failed to query sessions from {db_path}: {exc}")

        if not session_row:
            raise ParseError(f"session {sid} not found in {db_path}")

        session_id = session_row["id"]
        session = Session(id=session_id, agent=AGENT, file=path, subagent_of=subagent_of)

        cwd = session_row["cwd"]
        if cwd and isinstance(cwd, str):
            session.note_cwd(cwd)

        title = session_row["title"]
        if title and isinstance(title, str):
            session.title = clean_title(title)

        started_at = session_row["started_at"]
        if started_at is not None:
            try:
                s_ts = float(started_at)
                ts = s_ts / 1000.0 if s_ts > 1e11 else s_ts
                session.origin_ts = ts
                session.note_time(ts)
            except (ValueError, TypeError):
                pass

        # Query session_model_usage or session_model_usage_v21
        usage_table = next((t for t in ("session_model_usage", "session_model_usage_v21") if t in tables), None)
        usage_rows: List[dict] = []
        if usage_table:
            u_cols = {row[1] for row in cur.execute(f'PRAGMA table_info("{usage_table}")')}
            task_expr = 'u."task"' if "task" in u_cols else "''"
            first_expr = 'u."first_seen"' if "first_seen" in u_cols else "NULL"
            last_expr = 'u."last_seen"' if "last_seen" in u_cols else "NULL"
            u_query = f"""
                SELECT u.model, {task_expr} AS task, u.input_tokens, u.output_tokens,
                       u.cache_read_tokens, u.cache_write_tokens, u.reasoning_tokens,
                       {first_expr} AS first_seen, {last_expr} AS last_seen
                FROM "{usage_table}" u
                WHERE u.session_id = ?
            """
            try:
                cur.execute(u_query, (session_id,))
                usage_rows = [dict(r) for r in cur.fetchall()]
            except sqlite3.Error:
                usage_rows = []

        # Deduplicate usage rows if any
        has_main_task = any(not (r.get("task") or "") for r in usage_rows)
        records: List[dict] = []

        if usage_rows:
            records.extend(usage_rows)
            # If usage rows contain only auxiliary tasks without main task, add session summary row
            if not has_main_task:
                records.append({
                    "model": session_row["model"],
                    "task": "",
                    "input_tokens": session_row["input_tokens"],
                    "output_tokens": session_row["output_tokens"],
                    "cache_read_tokens": session_row["cache_read_tokens"],
                    "cache_write_tokens": session_row["cache_write_tokens"],
                    "reasoning_tokens": session_row["reasoning_tokens"],
                    "first_seen": started_at,
                    "last_seen": started_at,
                })
        else:
            records.append({
                "model": session_row["model"],
                "task": "",
                "input_tokens": session_row["input_tokens"],
                "output_tokens": session_row["output_tokens"],
                "cache_read_tokens": session_row["cache_read_tokens"],
                "cache_write_tokens": session_row["cache_write_tokens"],
                "reasoning_tokens": session_row["reasoning_tokens"],
                "first_seen": started_at,
                "last_seen": started_at,
            })

        for idx, r in enumerate(records):
            raw_ts = r.get("first_seen") or r.get("last_seen") or started_at
            ts = None
            if raw_ts is not None:
                try:
                    f_ts = float(raw_ts)
                    ts = f_ts / 1000.0 if f_ts > 1e11 else f_ts
                except (ValueError, TypeError):
                    ts = None

            if ts:
                session.note_time(ts)
                if session.origin_ts is None:
                    session.origin_ts = ts

            inp = int(r.get("input_tokens") or 0)
            out = int(r.get("output_tokens") or 0)
            cr = int(r.get("cache_read_tokens") or 0)
            cw = int(r.get("cache_write_tokens") or 0)
            reason = int(r.get("reasoning_tokens") or 0)
            thinking = min(reason, out) if out else reason

            if inp + out + cr + cw <= 0:
                continue

            model = r.get("model") or session_row["model"] or "hermes"
            task = r.get("task") or ""
            key = f"{AGENT}:{session.id}:{model}:{task or idx}"

            session.messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model=str(model),
                    input=inp,
                    output=out,
                    cache_read=cr,
                    cache_write=cw,
                    thinking=thinking,
                    cwd=session.cwd,
                    key=key,
                )
            )

    return session
