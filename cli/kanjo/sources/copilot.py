"""Copilot CLI: ``~/.copilot/session-state/<id>/events.jsonl`` (and ``session-store.db``).

Parses trajectory event streams from GitHub Copilot CLI. Uses session-state as the
primary source of truth (holding comprehensive turn events and modelMetrics),
falling back to session-store.db when session-state is absent.
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
from typing import Dict, List, Optional, Tuple

from .base import (
    Message,
    ParseError,
    Session,
    absolutize,
    env_dirs,
    extract_paths,
    git_branch,
    open_sqlite_ro,
    parse_iso,
    short_title,
)

AGENT = "copilot"


def roots() -> List[str]:
    return env_dirs("KANJO_COPILOT_DIR", ["~/.copilot"])


def _parse_yaml_simple(path: str) -> Dict[str, str]:
    """Parse flat key-value pairs from workspace.yaml without external YAML library."""
    data: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in data and v:
                        data[k] = v
    except OSError:
        pass
    return data


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(events_jsonl_or_db_session, None)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen = set()

    for root in dirs if dirs is not None else roots():
        if not os.path.exists(root):
            continue

        # Check if root is directly a session-state folder or contains one
        state_dir = os.path.join(root, "session-state") if os.path.isdir(os.path.join(root, "session-state")) else (
            root if os.path.basename(root) == "session-state" else None
        )

        has_state = False
        if state_dir and os.path.isdir(state_dir):
            for path in sorted(glob.glob(os.path.join(state_dir, "*", "events.jsonl"))):
                real = os.path.realpath(path)
                if real not in seen:
                    seen.add(real)
                    found.append((path, None))
                    has_state = True

        # Fallback to session-store.db if no events.jsonl files were found
        if not has_state:
            db_path = root if (os.path.isfile(root) and root.endswith(".db")) else os.path.join(root, "session-store.db")
            if os.path.isfile(db_path):
                try:
                    with open_sqlite_ro(db_path) as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT DISTINCT session_id FROM assistant_usage_events")
                        for (sid,) in cur.fetchall():
                            target = f"{db_path}::{sid}"
                            if target not in seen:
                                seen.add(target)
                                found.append((target, None))
                except (ParseError, sqlite3.Error):
                    pass

    return found


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if "::" in path:
        return _parse_db_session(path, subagent_of)
    return _parse_events_file(path, subagent_of)


def _parse_events_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if not os.path.isfile(path):
        raise ParseError("Copilot events file not found: %s" % path)

    session_dir = os.path.dirname(path)
    sid = os.path.basename(session_dir)

    session = Session(id=sid, agent=AGENT, file=path, subagent_of=subagent_of)

    # Read workspace.yaml metadata
    ws_file = os.path.join(session_dir, "workspace.yaml")
    ws_data = _parse_yaml_simple(ws_file) if os.path.isfile(ws_file) else {}

    cwd = ws_data.get("cwd") or ws_data.get("git_root")
    branch = ws_data.get("branch") or git_branch(cwd)
    repo = ws_data.get("repository")

    session.note_cwd(cwd)
    session.branch = branch
    if repo and cwd:
        session.remote_hints[cwd] = repo if "://" in repo else f"https://github.com/{repo}"

    ws_created = ws_data.get("created_at")
    if ws_created:
        session.origin_ts = parse_iso(ws_created)
        session.note_time(session.origin_ts)

    # Read events.jsonl
    events: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                stripped = line.strip()
                if stripped:
                    try:
                        events.append(json.loads(stripped))
                    except (ValueError, TypeError):
                        pass
    except OSError as exc:
        raise ParseError("cannot read Copilot events %s: %s" % (path, exc))

    user_title = None
    asst_messages: List[dict] = []
    shutdown_event = None

    for event in events:
        etype = event.get("type")
        edata = event.get("data") if isinstance(event.get("data"), dict) else {}
        ets = parse_iso(event.get("timestamp"))
        session.note_time(ets)

        if etype == "session.start" and session.origin_ts is None:
            session.origin_ts = ets

        elif etype == "user.message" and not user_title:
            content = edata.get("content")
            if isinstance(content, str) and content.strip():
                user_title = short_title(content)

        elif etype == "assistant.message":
            asst_messages.append(event)

        elif etype == "session.shutdown":
            shutdown_event = event

    session.title = user_title or short_title(ws_data.get("name"))

    # Extract messages from shutdown modelMetrics
    shutdown_data = shutdown_event.get("data") if (shutdown_event and isinstance(shutdown_event.get("data"), dict)) else {}
    model_metrics = shutdown_data.get("modelMetrics") if isinstance(shutdown_data.get("modelMetrics"), dict) else {}

    if model_metrics:
        # Use full usage breakdown from session.shutdown
        shutdown_ts = parse_iso(shutdown_event.get("timestamp")) or session.ended or session.started or 0.0
        for model_id, mdata in model_metrics.items():
            if not isinstance(mdata, dict):
                continue
            usage = mdata.get("usage") if isinstance(mdata.get("usage"), dict) else {}
            inp = int(usage.get("inputTokens") or 0)
            out = int(usage.get("outputTokens") or 0)
            cache_read = int(usage.get("cacheReadTokens") or 0)
            cache_write = int(usage.get("cacheWriteTokens") or 0)
            reasoning = int(usage.get("reasoningTokens") or 0)

            # Do not emit empty message if everything is zero
            if not (inp or out or cache_read or cache_write or reasoning):
                continue

            key = f"copilot:{sid}:{model_id}"
            session.messages.append(
                Message(
                    ts=shutdown_ts,
                    model=model_id,
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
    elif asst_messages:
        # Fallback to individual assistant.message events if shutdown was not recorded
        for amsg in asst_messages:
            adata = amsg.get("data") or {}
            model_id = adata.get("model") or "unknown"
            out = int(adata.get("outputTokens") or 0)
            msg_ts = parse_iso(amsg.get("timestamp")) or 0.0
            mid = adata.get("messageId") or amsg.get("id") or str(msg_ts)
            key = f"copilot:{sid}:{mid}"

            session.messages.append(
                Message(
                    ts=msg_ts,
                    model=model_id,
                    input=0,
                    output=out,
                    cache_read=0,
                    cache_write=0,
                    thinking=0,
                    cwd=session.cwd,
                    branch=session.branch,
                    key=key,
                )
            )

    # Tool / code changes paths
    code_changes = shutdown_data.get("codeChanges") if isinstance(shutdown_data.get("codeChanges"), dict) else {}
    files_modified = code_changes.get("filesModified")
    if isinstance(files_modified, list) and files_modified:
        tool_call_paths = []
        for fpath in files_modified:
            absp = absolutize(fpath, cwd)
            if absp:
                tool_call_paths.append(absp)
        if tool_call_paths:
            session.tool_paths.append(tool_call_paths)

    return session


def _parse_db_session(path: str, subagent_of: Optional[str] = None) -> Session:
    db_path, sid = path.split("::", 1)
    if not os.path.isfile(db_path):
        raise ParseError("Copilot session database not found: %s" % db_path)

    session = Session(id=sid, agent=AGENT, file=path, subagent_of=subagent_of)

    with open_sqlite_ro(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Query session metadata
        try:
            cur.execute("SELECT id, cwd, repository, branch, summary, created_at FROM sessions WHERE id = ?", (sid,))
            srow = cur.fetchone()
        except sqlite3.Error as exc:
            raise ParseError("failed to query sessions from %s: %s" % (db_path, exc))

        if not srow:
            raise ParseError("session %s not found in %s" % (sid, db_path))

        cwd = srow["cwd"]
        branch = srow["branch"] or git_branch(cwd)
        repo = srow["repository"]
        summary = srow["summary"]
        created_at = srow["created_at"]

        session.note_cwd(cwd)
        session.branch = branch
        session.title = short_title(summary)
        if repo and cwd:
            session.remote_hints[cwd] = repo if "://" in repo else f"https://github.com/{repo}"
        if created_at:
            session.origin_ts = parse_iso(created_at)
            session.note_time(session.origin_ts)

        # Query usage events
        try:
            cur.execute(
                """
                SELECT id, model, input_tokens, output_tokens, cache_read_tokens,
                       cache_write_tokens, reasoning_tokens, created_at
                FROM assistant_usage_events
                WHERE session_id = ?
                ORDER BY created_at, id
                """,
                (sid,),
            )
            usage_rows = cur.fetchall()
        except sqlite3.Error as exc:
            raise ParseError("failed to query assistant_usage_events for session %s: %s" % (sid, exc))

        for row in usage_rows:
            ts = parse_iso(row["created_at"]) or 0.0
            model = row["model"] or "unknown"
            inp = int(row["input_tokens"] or 0)
            out = int(row["output_tokens"] or 0)
            cache_read = int(row["cache_read_tokens"] or 0)
            cache_write = int(row["cache_write_tokens"] or 0)
            reasoning = int(row["reasoning_tokens"] or 0)
            row_id = row["id"]
            key = f"copilot:{sid}:{row_id}"

            session.note_time(ts)
            session.messages.append(
                Message(
                    ts=ts,
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

    return session
