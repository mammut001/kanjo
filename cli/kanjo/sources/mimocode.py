"""MiMo Code coding agent: ``~/Library/Application Support/mimocode/data/mimocode.db`` (SQLite).

Reads session metadata and message JSON events recorded by MiMo Code.
"""

from __future__ import annotations

import glob
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

AGENT = "mimocode"


def roots() -> List[str]:
    explicit = (
        os.environ.get("KANJO_MIMOCODE_DIR")
        or os.environ.get("TOKEI_MIMOCODE_DB")
        or os.environ.get("MIMOCODE_HOME")
    )
    if explicit:
        paths = []
        for p in split_path_list(explicit):
            exp = winsupport.abspath(winsupport.expanduser(p))
            if os.path.isdir(os.path.join(exp, "data")):
                paths.append(os.path.join(exp, "data"))
            else:
                paths.append(exp)
        return paths
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    if winsupport.is_windows():
        # MiMo Code is a macOS-only desktop app; an explicit KANJO_MIMOCODE_DIR is
        # the only way to scan it on Windows.
        return []
    candidates = [
        winsupport.expanduser("~/Library/Application Support/mimocode"),
        winsupport.expanduser("~/Library/Application Support/mimocode/data"),
        winsupport.expanduser("~/.local/share/mimocode"),
        winsupport.expanduser("~/.local/share/mimocode/data"),
    ]
    existing = [winsupport.abspath(c) for c in candidates if os.path.exists(c)]
    return existing[:1] if existing else [winsupport.abspath(candidates[0])]


def _db_paths_for_root(root: str) -> List[str]:
    if os.path.isfile(root) and (root.endswith(".db") or root.endswith(".sqlite")):
        return [root]
    results: List[str] = []
    for pattern in ("mimocode.db", "data/mimocode.db", "mimocode-*.db", "data/mimocode-*.db", "*.db", "*.sqlite"):
        for p in glob.glob(os.path.join(root, pattern)):
            if os.path.isfile(p) and p not in results:
                results.append(p)
    return results


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(db_path::session_id, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    for root in dirs if dirs is not None else roots():
        for db in _db_paths_for_root(root):
            try:
                with open_sqlite_ro(db) as conn:
                    cur = conn.cursor()
                    tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    sess_table = next((t for t in ("session", "session_v2") if t in tables), None)
                    if sess_table:
                        cols = {r[1] for r in cur.execute(f'PRAGMA table_info("{sess_table}")')}
                        p_expr = "parent_id" if "parent_id" in cols else "NULL"
                        cur.execute(f'SELECT id, {p_expr} FROM "{sess_table}" WHERE id IS NOT NULL')
                        for sid, parent in cur:
                            key = f"{db}::{sid}"
                            if key not in seen:
                                seen.add(key)
                                found.append((key, parent or None))
                    elif "message" in tables or "session_message" in tables:
                        msg_table = "message" if "message" in tables else "session_message"
                        cur.execute(f'SELECT DISTINCT session_id FROM "{msg_table}" WHERE session_id IS NOT NULL AND session_id != ""')
                        for (sid,) in cur:
                            key = f"{db}::{sid}"
                            if key not in seen:
                                seen.add(key)
                                found.append((key, None))
            except (ParseError, sqlite3.Error):
                continue
    return found


def _parse_ts(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        f = float(val)
        return f / 1000.0 if f > 1e11 else f
    if isinstance(val, str) and val.strip():
        from .base import parse_iso
        return parse_iso(val.strip())
    return None


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if "::" in path:
        db_path, sid = path.split("::", 1)
    else:
        db_path, sid = path, None

    if not os.path.isfile(db_path):
        raise ParseError(f"MiMo Code database not found: {db_path}")

    with open_sqlite_ro(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        session_id = sid or "mimocode_session"
        session = Session(id=session_id, agent=AGENT, file=path, subagent_of=subagent_of)

        sess_table = next((t for t in ("session", "session_v2") if t in tables), None)
        if sess_table:
            cols = {r[1] for r in cur.execute(f'PRAGMA table_info("{sess_table}")')}
            dir_expr = "directory" if "directory" in cols else "NULL"
            title_expr = "title" if "title" in cols else "NULL"
            time_expr = "time_created" if "time_created" in cols else "NULL"
            parent_expr = "parent_id" if "parent_id" in cols else "NULL"
            try:
                if sid:
                    cur.execute(
                        f'SELECT id, {dir_expr} AS directory, {title_expr} AS title, {time_expr} AS time_created, {parent_expr} AS parent_id FROM "{sess_table}" WHERE id = ?',
                        (sid,),
                    )
                else:
                    cur.execute(
                        f'SELECT id, {dir_expr} AS directory, {title_expr} AS title, {time_expr} AS time_created, {parent_expr} AS parent_id FROM "{sess_table}" LIMIT 1'
                    )
                srow = cur.fetchone()
                if srow:
                    session.id = str(srow["id"])
                    if srow["parent_id"] and session.subagent_of is None:
                        session.subagent_of = str(srow["parent_id"])
                    if srow["directory"]:
                        session.note_cwd(str(srow["directory"]))
                    if srow["title"]:
                        session.title = clean_title(str(srow["title"]))
                    c_ts = _parse_ts(srow["time_created"])
                    if c_ts:
                        session.origin_ts = c_ts
                        session.note_time(c_ts)
            except sqlite3.Error:
                pass

        msg_table = next((t for t in ("message", "session_message") if t in tables), None)
        if not msg_table:
            return session

        try:
            if sid:
                cur.execute(
                    f'SELECT id, time_created, data FROM "{msg_table}" WHERE session_id = ? AND data IS NOT NULL ORDER BY time_created ASC, id ASC',
                    (sid,),
                )
            else:
                cur.execute(
                    f'SELECT id, time_created, data FROM "{msg_table}" WHERE data IS NOT NULL ORDER BY time_created ASC, id ASC'
                )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise ParseError(f"failed to query {msg_table} from {db_path}: {exc}")

        for r in rows:
            raw_data = r["data"]
            data = None
            if isinstance(raw_data, str) and raw_data.strip():
                try:
                    data = json.loads(raw_data)
                except (ValueError, TypeError):
                    continue
            elif isinstance(raw_data, dict):
                data = raw_data
            if not isinstance(data, dict):
                continue

            role = data.get("role")
            if role == "user":
                if session.title is None:
                    txt = data.get("content") or data.get("text")
                    if isinstance(txt, str) and txt.strip():
                        session.title = clean_title(txt.strip())
                continue

            if role != "assistant":
                continue

            tokens = data.get("tokens") or {}
            if not isinstance(tokens, dict):
                continue

            inp = max(int(tokens.get("input") or 0), 0)
            out = max(int(tokens.get("output") or 0), 0)
            reason = max(int(tokens.get("reasoning") or 0), 0)
            cache = tokens.get("cache") or {}
            cr = max(int(cache.get("read") or 0), 0) if isinstance(cache, dict) else 0
            cw = max(int(cache.get("write") or 0), 0) if isinstance(cache, dict) else 0
            thinking = min(reason, out) if out else reason

            if inp + out + cr + cw <= 0:
                continue

            time_obj = data.get("time") or {}
            t_created = time_obj.get("created") if isinstance(time_obj, dict) else None
            ts = _parse_ts(t_created) or _parse_ts(r["time_created"])

            if ts:
                session.note_time(ts)
                if session.origin_ts is None:
                    session.origin_ts = ts

            model_val = data.get("modelID") or data.get("model") or "MiMo-V2.5-Pro"
            if isinstance(model_val, dict):
                model_name = model_val.get("id") or model_val.get("name") or "MiMo-V2.5-Pro"
            else:
                model_name = str(model_val)

            msg_id = data.get("id") or r["id"]
            key = f"{AGENT}:{session.id}:{msg_id}"

            session.messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model=model_name,
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
