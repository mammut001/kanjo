"""Command Code: ``~/.commandcode/projects/<slug>/<session-id>.jsonl``.

Line 0 contains session metadata: ``{"type": "session", "id": "...", "cwd": "...", "timestamp": "..."}``.
Assistant message lines contain model, timestamp, and token usage under ``usage``:
``inputTokens``, ``outputTokens``, ``cacheReadTokens``, ``cacheWriteTokens``.
Tool calls in content blocks are scanned for touched paths.
Checkpoints files (``*.checkpoints.jsonl``) are excluded.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional, Set, Tuple

from .base import Message, ParseError, Session, env_dirs, paths_from_args, parse_iso, short_title, unique

AGENT = "commandcode"
PATH_KEYS = {
    "file_path", "path", "notebook_path", "filepath", "directory", "dir", "cwd",
    "workdir", "paths", "target_file", "absolute_path"
}
CMD_KEYS = {"command", "cmd"}


def roots() -> List[str]:
    explicit = os.environ.get("KANJO_COMMANDCODE_DIR")
    if explicit:
        paths = []
        for p in explicit.split(os.pathsep):
            exp = os.path.expanduser(p)
            if os.path.isdir(os.path.join(exp, "projects")):
                paths.append(os.path.join(exp, "projects"))
            else:
                paths.append(exp)
        return paths
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    return [os.path.expanduser("~/.commandcode/projects")]


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(jsonl_path, parent session id)]"""
    found = []
    seen = set()
    for root in dirs if dirs is not None else roots():
        if not os.path.isdir(root):
            continue
        candidates = (
            glob.glob(os.path.join(root, "*", "*.jsonl"))
            + glob.glob(os.path.join(root, "*.jsonl"))
        )
        for path in sorted(candidates):
            if path.endswith(".checkpoints.jsonl"):
                continue
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                found.append((path, None))
    return found


def _user_text(message: dict) -> Optional[str]:
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str) and t.strip():
                    return t.strip()
    return None


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    stem = os.path.splitext(os.path.basename(path))[0]
    session = Session(id=stem, agent=AGENT, file=path, subagent_of=subagent_of)

    tools: Dict[str, Set[str]] = {}
    tool_order: List[str] = []
    messages: List[Message] = []

    try:
        handle = open(path, "r", encoding="utf-8")
    except OSError as exc:
        raise ParseError(str(exc))

    with handle:
        for idx, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if not isinstance(obj, dict):
                continue

            kind = obj.get("type")

            # Line 0 or session header
            if kind == "session":
                if obj.get("id"):
                    session.id = str(obj["id"])
                cwd = obj.get("cwd")
                if isinstance(cwd, str) and cwd:
                    session.note_cwd(cwd)
                ts = parse_iso(obj.get("timestamp"))
                if ts is not None:
                    if session.origin_ts is None:
                        session.origin_ts = ts
                    session.note_time(ts)
                continue

            if kind != "message":
                continue

            ts = parse_iso(obj.get("timestamp"))
            session.note_time(ts)

            msg = obj.get("message")
            msg_dict = msg if isinstance(msg, dict) else {}
            role = msg_dict.get("role")

            if role == "user":
                if session.title is None:
                    t = short_title(_user_text(msg_dict))
                    if t:
                        session.title = t
                continue

            # Assistant messages with usage
            usage = obj.get("usage")
            if not isinstance(usage, dict):
                continue

            # Tool calls
            content = msg_dict.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tid = block.get("id") or f"tool_{len(tool_order)}"
                        args = block.get("input")
                        found_paths = paths_from_args(args, session.cwd, PATH_KEYS, CMD_KEYS)
                        if tid not in tools:
                            tools[tid] = set()
                            tool_order.append(tid)
                        tools[tid].update(found_paths)

            inp = int(usage.get("inputTokens") or 0)
            out = int(usage.get("outputTokens") or 0)
            cache_r = int(usage.get("cacheReadTokens") or 0)
            cache_w = int(usage.get("cacheWriteTokens") or 0)
            non_cached_in = max(0, inp - cache_r)

            meta = msg_dict.get("meta") if isinstance(msg_dict.get("meta"), dict) else {}
            mid = obj.get("id") or meta.get("messageId") or f"line_{idx}"
            model = obj.get("model") or "unknown"

            messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model=str(model),
                    input=non_cached_in,
                    output=out,
                    cache_read=cache_r,
                    cache_write=cache_w,
                    thinking=0,
                    cwd=session.cwd,
                    branch=session.branch,
                    key=f"commandcode:{mid}" if mid else None,
                )
            )

    session.messages = messages
    session.tool_paths = [unique(sorted(tools[t])) for t in tool_order if tools[t]]
    return session
