"""Devin coding agent: ``~/.local/share/devin/cli/sessions.db`` (SQLite).

Reads session metadata and message node trees from Devin CLI database.
Deduplicates sibling message nodes that share identical metrics and microsecond timestamps.
"""

from __future__ import annotations

import json
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

AGENT = "devin"


def roots() -> List[str]:
    explicit = (
        os.environ.get("KANJO_DEVIN_DIR")
        or os.environ.get("TOKEI_DEVIN_CLI_DB")
        or os.environ.get("KANJO_DEVIN_CLI_DB")
    )
    if explicit:
        return [winsupport.abspath(winsupport.expanduser(p)) for p in split_path_list(explicit) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    if winsupport.is_windows():
        # Devin CLI is an XDG-style tool: same dot-dir under %USERPROFILE%, plus
        # %LOCALAPPDATA%\devin for the desktop build.
        candidates = [
            winsupport.join(winsupport.local_data_dir("devin"), "cli"),
            winsupport.expanduser("~/.devin/cli"),
            winsupport.expanduser("~/.config/devin"),
        ]
    else:
        candidates = [
            winsupport.expanduser("~/.local/share/devin/cli"),
            winsupport.expanduser("~/Library/Application Support/devin/cli"),
            winsupport.expanduser("~/.config/devin"),
        ]
    existing = [winsupport.abspath(c) for c in candidates if os.path.exists(c)]
    return existing[:1] if existing else [winsupport.abspath(candidates[0])]


def _db_path(root: str) -> Optional[str]:
    if os.path.isfile(root) and (root.endswith(".db") or root.endswith(".sqlite")):
        return root
    for name in ("sessions.db", "cli/sessions.db", "db.sqlite"):
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
                if "sessions" in tables:
                    cur.execute("SELECT id FROM sessions WHERE id IS NOT NULL")
                    for (sid,) in cur:
                        if sid:
                            key = f"{db}::{sid}"
                            if key not in seen:
                                seen.add(key)
                                found.append((key, None))
                elif "message_nodes" in tables:
                    cur.execute("SELECT DISTINCT session_id FROM message_nodes WHERE session_id IS NOT NULL")
                    for (sid,) in cur:
                        if sid:
                            key = f"{db}::{sid}"
                            if key not in seen:
                                seen.add(key)
                                found.append((key, None))
        except (ParseError, sqlite3.Error):
            continue
    return found


def _parse_epoch(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        f = float(value)
        return f / 1000.0 if f > 1e11 else f
    if isinstance(value, str) and value.strip():
        from .base import parse_iso
        return parse_iso(value.strip())
    return None


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if "::" in path:
        db_path, sid = path.split("::", 1)
    else:
        db_path, sid = path, None

    if not os.path.isfile(db_path):
        raise ParseError(f"Devin database not found: {db_path}")

    with open_sqlite_ro(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "message_nodes" not in tables and "sessions" not in tables:
            raise ParseError(f"neither message_nodes nor sessions found in {db_path}")

        session_id = sid or "devin_session"
        session = Session(id=session_id, agent=AGENT, file=path, subagent_of=subagent_of)

        session_model = None
        if "sessions" in tables:
            cols = {row[1] for row in cur.execute("PRAGMA table_info(sessions)")}
            workdir_expr = "working_directory" if "working_directory" in cols else "NULL"
            model_expr = "model" if "model" in cols else "NULL"
            title_expr = "title" if "title" in cols else "NULL"
            try:
                if sid:
                    cur.execute(f"SELECT id, {model_expr} AS model, {workdir_expr} AS workdir, {title_expr} AS title FROM sessions WHERE id = ?", (sid,))
                    srow = cur.fetchone()
                else:
                    cur.execute(f"SELECT id, {model_expr} AS model, {workdir_expr} AS workdir, {title_expr} AS title FROM sessions LIMIT 1")
                    srow = cur.fetchone()
                if srow:
                    session_id = str(srow["id"])
                    session.id = session_id
                    if srow["workdir"]:
                        session.note_cwd(str(srow["workdir"]))
                    if srow["title"]:
                        session.title = clean_title(str(srow["title"]))
                    if srow["model"]:
                        session_model = str(srow["model"]).strip()
            except sqlite3.Error:
                pass

        if "message_nodes" not in tables:
            return session

        node_cols = {row[1] for row in cur.execute("PRAGMA table_info(message_nodes)")}
        node_expr = "node_id" if "node_id" in node_cols else "rowid"
        try:
            if sid:
                cur.execute(
                    f"SELECT session_id, {node_expr} AS node_id, chat_message, created_at FROM message_nodes WHERE session_id = ? ORDER BY created_at ASC, {node_expr} ASC",
                    (sid,),
                )
            else:
                cur.execute(
                    f"SELECT session_id, {node_expr} AS node_id, chat_message, created_at FROM message_nodes ORDER BY created_at ASC, {node_expr} ASC"
                )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise ParseError(f"failed to query message_nodes from {db_path}: {exc}")

        seen: Set[Tuple[Any, ...]] = set()
        for r in rows:
            raw_msg = r["chat_message"]
            if isinstance(raw_msg, (bytes, bytearray)):
                try:
                    raw_msg = bytes(raw_msg).decode("utf-8")
                except UnicodeDecodeError:
                    continue
            try:
                root = json.loads(raw_msg)
            except (ValueError, TypeError):
                continue
            if not isinstance(root, dict):
                continue

            metadata = root.get("metadata")
            if not isinstance(metadata, dict):
                continue

            metrics = metadata.get("metrics")
            if not isinstance(metrics, dict):
                continue

            inp = max(int(metrics.get("input_tokens") or 0), 0)
            out = max(int(metrics.get("output_tokens") or 0), 0)
            cr = max(int(metrics.get("cache_read_tokens") or 0), 0)
            cw = max(int(metrics.get("cache_creation_tokens") or 0), 0)
            reason = max(int(metrics.get("reasoning_tokens") or 0), 0)
            thinking = min(reason, out) if out else reason

            if inp + out + cr + cw <= 0:
                continue

            stamp_source = metadata.get("created_at")
            ts = _parse_epoch(stamp_source) if stamp_source is not None else None
            if ts is None:
                ts = _parse_epoch(r["created_at"])
            if ts is None or ts <= 0:
                continue

            session.note_time(ts)
            if session.origin_ts is None:
                session.origin_ts = ts

            gen_model = metadata.get("generation_model")
            model = (gen_model.strip() if isinstance(gen_model, str) and gen_model.strip() else None) or session_model or "devin"

            node_id = r["node_id"]
            # Deduplicate mirroring sibling nodes:
            # same timestamp + same metrics + same model within this session
            dedup_key = (stamp_source if stamp_source is not None else node_id, model, inp, out, cr, cw)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            key = f"{AGENT}:{session.id}:{node_id}"

            session.messages.append(
                Message(
                    ts=ts,
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
