"""OpenClaw coding agent: ``~/.openclaw`` (JSONL transcripts and SQLite databases).

Supports:
- JSONL sessions: ``~/.openclaw/agents/<agent>/sessions/<id>.jsonl``
- SQLite agent databases discovered via ``state/openclaw.sqlite`` or direct SQLite storage,
  reading the ``transcript_events`` table.
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

AGENT = "openclaw"


def roots() -> List[str]:
    explicit = os.environ.get("KANJO_OPENCLAW_DIR") or os.environ.get("OPENCLAW_STATE_DIR")
    if explicit:
        return [os.path.abspath(winsupport.expanduser(p)) for p in split_path_list(explicit) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    return [os.path.abspath(winsupport.expanduser("~/.openclaw"))]


def _openclaw_agent_dbs(root: str) -> List[str]:
    dbs: List[str] = []
    seen: Set[str] = set()
    state_candidates = [
        os.path.join(root, "state", "openclaw.sqlite"),
        os.path.join(root, "openclaw.sqlite"),
        os.path.join(root, "tasks", "runs.sqlite"),
    ]
    for sc in state_candidates:
        if not os.path.isfile(sc):
            continue
        try:
            with open_sqlite_ro(sc) as conn:
                cur = conn.cursor()
                tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "agent_databases" in tables:
                    cur.execute("SELECT path FROM agent_databases")
                    for (raw_path,) in cur:
                        if isinstance(raw_path, str) and raw_path.strip():
                            exp = os.path.expandvars(winsupport.expanduser(raw_path.strip()))
                            res = exp if os.path.isabs(exp) else os.path.join(root, exp)
                            real = os.path.realpath(res)
                            if os.path.isfile(real) and real not in seen:
                                seen.add(real)
                                dbs.append(real)
                if "transcript_events" in tables:
                    real = os.path.realpath(sc)
                    if real not in seen:
                        seen.add(real)
                        dbs.append(real)
        except (ParseError, sqlite3.Error):
            continue

    # Also check any .db or .sqlite files directly under root
    for f in glob.glob(os.path.join(root, "*.db")) + glob.glob(os.path.join(root, "*.sqlite")):
        real = os.path.realpath(f)
        if real in seen or not os.path.isfile(real):
            continue
        try:
            with open_sqlite_ro(real) as conn:
                cur = conn.cursor()
                tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "transcript_events" in tables:
                    seen.add(real)
                    dbs.append(real)
        except (ParseError, sqlite3.Error):
            continue

    return dbs


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(file_path_or_db_with_sid, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    for root in dirs if dirs is not None else roots():
        if not os.path.isdir(root):
            if os.path.isfile(root) and root.endswith(".jsonl"):
                found.append((root, None))
            continue

        # 1. JSONL files
        jsonl_candidates = (
            glob.glob(os.path.join(root, "agents", "*", "sessions", "*.jsonl"))
            + glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)
        )
        for path in sorted(jsonl_candidates):
            if path.endswith(".trajectory.jsonl"):
                continue
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                found.append((path, None))

        # 2. SQLite agent databases
        agent_dbs = _openclaw_agent_dbs(root)
        for db in agent_dbs:
            try:
                with open_sqlite_ro(db) as conn:
                    cur = conn.cursor()
                    cur.execute(
                        "SELECT DISTINCT session_id FROM transcript_events WHERE session_id IS NOT NULL AND session_id != ''"
                    )
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


def _handle_event(
    event: dict,
    session: Session,
    fallback_model: str,
    idx: int,
) -> None:
    if not isinstance(event, dict):
        return

    kind = event.get("type")
    if kind == "session":
        sid = event.get("id")
        if sid:
            session.id = str(sid)
        cwd = event.get("cwd")
        if isinstance(cwd, str) and cwd:
            session.note_cwd(cwd)
        ts = _parse_ts(event.get("timestamp") or event.get("createdAt"))
        if ts:
            if session.origin_ts is None:
                session.origin_ts = ts
            session.note_time(ts)
        return

    cwd = event.get("cwd")
    if isinstance(cwd, str) and cwd:
        session.note_cwd(cwd)

    msg = event.get("message")
    if not isinstance(msg, dict):
        return

    ts = _parse_ts(event.get("timestamp") or msg.get("timestamp"))
    if ts:
        if session.origin_ts is None:
            session.origin_ts = ts
        session.note_time(ts)

    role = msg.get("role")
    if role == "user":
        if session.title is None:
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                session.title = clean_title(content.strip())
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("text"):
                        session.title = clean_title(b["text"])
                        break
        return

    if role != "assistant":
        return

    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return

    inp = max(int(usage.get("input") or 0), 0)
    out = max(int(usage.get("output") or 0), 0)
    cr = max(int(usage.get("cacheRead") or usage.get("cache_read") or 0), 0)
    cw = max(int(usage.get("cacheWrite") or usage.get("cache_write") or 0), 0)
    reason = max(int(usage.get("reasoningTokens") or usage.get("reasoning") or 0), 0)
    thinking = min(reason, out) if out else reason

    if inp + out + cr + cw <= 0:
        return

    model = (
        msg.get("responseModel")
        or msg.get("model")
        or fallback_model
        or "openclaw"
    )

    mid = event.get("id") or msg.get("id") or f"evt_{idx}"
    key = f"{AGENT}:{session.id}:{mid}"

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


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if "::" in path:
        db_path, sid = path.split("::", 1)
        if not os.path.isfile(db_path):
            raise ParseError(f"OpenClaw database not found: {db_path}")

        session = Session(id=sid, agent=AGENT, file=path, subagent_of=subagent_of)
        with open_sqlite_ro(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            tables = {r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}

            fallback_model = "openclaw"
            if "session_windows" in tables:
                try:
                    cur.execute("SELECT model FROM session_windows WHERE session_id = ?", (sid,))
                    row = cur.fetchone()
                    if row and row["model"]:
                        fallback_model = str(row["model"])
                except sqlite3.Error:
                    pass

            cols = {r[1] for r in cur.execute("PRAGMA table_info(transcript_events)")}
            json_expr = "event_json" if "event_json" in cols else "NULL"
            zstd_expr = "event_zstd" if "event_zstd" in cols else "NULL"
            cur.execute(
                f"SELECT seq, created_at, {json_expr} AS event_json, {zstd_expr} AS event_zstd "
                f"FROM transcript_events WHERE session_id = ? ORDER BY seq ASC",
                (sid,),
            )
            for idx, r in enumerate(cur.fetchall()):
                raw_json = r["event_json"]
                event = None
                if isinstance(raw_json, str) and raw_json.strip():
                    try:
                        event = json.loads(raw_json)
                    except (ValueError, TypeError):
                        event = None
                elif r["event_zstd"]:
                    try:
                        import zstandard  # type: ignore
                        dctx = zstandard.ZstdDecompressor()
                        decompressed = dctx.decompress(r["event_zstd"], max_output_size=4 * 1024 * 1024)
                        event = json.loads(decompressed.decode("utf-8"))
                    except Exception:
                        event = None

                if isinstance(event, dict):
                    if "timestamp" not in event and r["created_at"]:
                        event["timestamp"] = r["created_at"]
                    _handle_event(event, session, fallback_model, idx)

        return session

    # JSONL file
    if not os.path.isfile(path):
        raise ParseError(f"OpenClaw session file not found: {path}")

    stem = os.path.splitext(os.path.basename(path))[0]
    session = Session(id=stem, agent=AGENT, file=path, subagent_of=subagent_of)

    try:
        handle = open(path, "r", encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise ParseError(str(exc))

    with handle:
        for idx, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            _handle_event(event, session, "openclaw", idx)

    return session
