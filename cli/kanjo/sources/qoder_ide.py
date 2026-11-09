"""Qoder IDE: ``~/Library/Application Support/Qoder/SharedClientCache/cache/db/local.db`` (SQLite).

Reads session metadata and message token usage from the Qoder IDE local database.
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

AGENT = "qoder_ide"


def roots() -> List[str]:
    explicit = (
        os.environ.get("KANJO_QODER_IDE_DIR")
        or os.environ.get("TOKEI_QODER_IDE_DB")
        or os.environ.get("KANJO_QODER_IDE_DB")
    )
    if explicit:
        return [os.path.abspath(os.path.expanduser(p)) for p in explicit.split(os.pathsep) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    candidates = [
        os.path.expanduser("~/Library/Application Support/Qoder/SharedClientCache/cache/db"),
        os.path.expanduser("~/Library/Application Support/Qoder"),
    ]
    existing = [os.path.abspath(c) for c in candidates if os.path.exists(c)]
    return existing[:1] if existing else [os.path.abspath(candidates[0])]


def _db_path(root: str) -> Optional[str]:
    if os.path.isfile(root) and (root.endswith(".db") or root.endswith(".sqlite")):
        return root
    for cand_name in (
        "local.db",
        "SharedClientCache/cache/db/local.db",
        "cache/db/local.db",
        "db/local.db",
    ):
        cand = os.path.join(root, cand_name)
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
                if "chat_message" not in tables:
                    continue
                cur.execute(
                    "SELECT DISTINCT session_id FROM chat_message WHERE session_id IS NOT NULL AND session_id != ''"
                )
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
        raise ParseError(f"Qoder IDE database not found: {db_path}")

    with open_sqlite_ro(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "chat_message" not in tables:
            raise ParseError(f"chat_message table not found in {db_path}")

        session_id = sid or "qoder_ide_session"
        session = Session(id=session_id, agent=AGENT, file=path, subagent_of=subagent_of)

        # Optional session metadata
        if "chat_session" in tables:
            cols = {row[1] for row in cur.execute("PRAGMA table_info(chat_session)")}
            cwd_col = next((c for c in ("cwd", "workspace", "directory", "project_path") if c in cols), None)
            title_col = next((c for c in ("title", "name", "topic") if c in cols), None)
            sel_cols = ["session_id"]
            if cwd_col:
                sel_cols.append(cwd_col)
            if title_col:
                sel_cols.append(title_col)
            try:
                cur.execute(f"SELECT {', '.join(sel_cols)} FROM chat_session WHERE session_id = ?", (session_id,))
                srow = cur.fetchone()
                if srow:
                    if cwd_col and srow[cwd_col]:
                        session.note_cwd(srow[cwd_col])
                    if title_col and srow[title_col]:
                        session.title = clean_title(srow[title_col])
            except sqlite3.Error:
                pass

        # Query messages
        msg_cols = {row[1] for row in cur.execute("PRAGMA table_info(chat_message)")}
        req_col = "request_id" if "request_id" in msg_cols else "id"
        try:
            if sid:
                cur.execute(
                    f"SELECT id, {req_col} AS req_id, token_info, model_info, gmt_create FROM chat_message WHERE session_id = ? ORDER BY gmt_create ASC, id ASC",
                    (sid,),
                )
            else:
                cur.execute(
                    f"SELECT id, {req_col} AS req_id, token_info, model_info, gmt_create FROM chat_message ORDER BY gmt_create ASC, id ASC"
                )
            rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise ParseError(f"failed to query chat_message from {db_path}: {exc}")

        for row in rows:
            gmt_create = row["gmt_create"]
            ts = None
            if gmt_create is not None:
                try:
                    f_ts = float(gmt_create)
                    ts = f_ts / 1000.0 if f_ts > 1e11 else f_ts
                except (ValueError, TypeError):
                    ts = None

            if ts:
                session.note_time(ts)
                if session.origin_ts is None:
                    session.origin_ts = ts

            raw_tok = row["token_info"]
            tok: dict = {}
            if isinstance(raw_tok, str) and raw_tok.strip():
                try:
                    tok = json.loads(raw_tok)
                except (ValueError, TypeError):
                    tok = {}
            elif isinstance(raw_tok, dict):
                tok = raw_tok

            raw_model = row["model_info"]
            mod: dict = {}
            if isinstance(raw_model, str) and raw_model.strip():
                try:
                    mod = json.loads(raw_model)
                except (ValueError, TypeError):
                    mod = {}
            elif isinstance(raw_model, dict):
                mod = raw_model

            prompt_tok = int(tok.get("prompt_tokens") or tok.get("promptTokens") or 0)
            comp_tok = int(tok.get("completion_tokens") or tok.get("completionTokens") or 0)
            cached_tok = int(tok.get("cached_tokens") or tok.get("cachedTokens") or 0)
            reason_tok = int(tok.get("reasoning_tokens") or tok.get("reasoningTokens") or 0)

            inp = max(0, prompt_tok - cached_tok)
            out = comp_tok
            cr = cached_tok
            cw = 0
            thinking = min(reason_tok, out) if out else reason_tok

            if inp + out + cr + cw <= 0:
                continue

            model_name = (
                mod.get("model_key")
                or mod.get("modelKey")
                or mod.get("model_name")
                or mod.get("modelName")
                or "qoder-ide"
            )

            req_id = row["req_id"] or row["id"]
            key = f"{AGENT}:{session.id}:{req_id}"

            session.messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model=str(model_name),
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
