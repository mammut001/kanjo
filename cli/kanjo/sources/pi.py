"""Pi coding agent: ``~/.pi/agent/sessions/<encoded-cwd>/<timestamp>_<id>.jsonl``.

Each JSONL file represents a single session.
Line 0 / session header contains metadata: ``{"type": "session", "id": "...", "cwd": "...", "timestamp": "..."}``.
Assistant message lines contain role, model, provider, timestamp, and token usage under ``usage``:
``input``, ``output``, ``cacheRead``, ``cacheWrite``, ``reasoning``, ``totalTokens``.
Tool calls in content blocks (type ``toolCall``) are scanned for touched paths.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional, Set, Tuple

from .. import winsupport
from .base import (
    Message,
    ParseError,
    Session,
    clean_title,
    env_dirs,
    parse_iso,
    paths_from_args,
    unique,
    split_path_list,
)

AGENT = "pi"
PATH_KEYS = {
    "file_path", "path", "notebook_path", "filepath", "directory", "dir", "cwd",
    "workdir", "paths", "target_file", "absolute_path"
}
CMD_KEYS = {"command", "cmd"}


def roots(agent: str = "pi") -> List[str]:
    if agent == "omp":
        explicit = (
            os.environ.get("KANJO_OMP_DIR")
            or os.environ.get("OMP_CODING_AGENT_SESSION_DIR")
        )
        default_dir = "~/.omp/agent/sessions"
    elif agent == "prime_agent":
        explicit = (
            os.environ.get("KANJO_PRIME_AGENT_DIR")
            or os.environ.get("PRIME_AGENT_SESSION_DIR")
            or os.environ.get("PRIME_AGENT_CODING_AGENT_SESSION_DIR")
            or os.environ.get("PRIME_AGENT_CODING_AGENT_DIR")
        )
        default_dir = "~/.prime/agent/sessions"
    else:
        explicit = (
            os.environ.get("KANJO_PI_DIR")
            or os.environ.get("PI_CODING_AGENT_SESSION_DIR")
            or os.environ.get("PI_CODING_AGENT_DIR")
        )
        default_dir = "~/.pi/agent/sessions"

    if explicit:
        paths = []
        for p in split_path_list(explicit):
            exp = winsupport.expanduser(p)
            if os.path.isdir(os.path.join(exp, "agent", "sessions")):
                paths.append(os.path.join(exp, "agent", "sessions"))
            elif os.path.isdir(os.path.join(exp, "sessions")):
                paths.append(os.path.join(exp, "sessions"))
            else:
                paths.append(exp)
        return paths
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    return [winsupport.expanduser(default_dir)]


def discover(dirs: Optional[List[str]] = None, agent: str = "pi") -> List[Tuple[str, Optional[str]]]:
    """[(jsonl_path, parent session id)]"""
    found = []
    seen = set()
    for root in dirs if dirs is not None else roots(agent=agent):
        if not os.path.isdir(root):
            continue
        candidates = (
            glob.glob(os.path.join(root, "*", "*.jsonl"))
            + glob.glob(os.path.join(root, "*.jsonl"))
        )
        if not candidates:
            candidates = glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)
        for path in sorted(candidates):
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


def parse_file(path: str, subagent_of: Optional[str] = None, agent: str = "pi") -> Session:
    stem = os.path.splitext(os.path.basename(path))[0]
    session = Session(id=stem, agent=agent, file=path, subagent_of=subagent_of)

    tools: Dict[str, Set[str]] = {}
    tool_order: List[str] = []
    messages: List[Message] = []
    current_model: Optional[str] = None
    current_provider: Optional[str] = None

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

            if kind == "session":
                sid = obj.get("id")
                if sid:
                    session.id = str(sid)
                cwd = obj.get("cwd")
                if isinstance(cwd, str) and cwd:
                    session.note_cwd(cwd)
                ts = parse_iso(obj.get("timestamp"))
                if ts is not None:
                    if session.origin_ts is None:
                        session.origin_ts = ts
                    session.note_time(ts)
                continue

            if kind == "model_change":
                if obj.get("modelId"):
                    current_model = str(obj.get("modelId"))
                if obj.get("provider"):
                    current_provider = str(obj.get("provider"))
                continue

            if kind != "message":
                continue

            msg = obj.get("message")
            if not isinstance(msg, dict):
                continue

            ts = parse_iso(obj.get("timestamp"))
            if ts is None:
                raw_ts = msg.get("timestamp")
                if isinstance(raw_ts, (int, float)):
                    ts = raw_ts / 1000.0 if raw_ts > 1e11 else float(raw_ts)
            session.note_time(ts)

            role = msg.get("role")
            if role == "user":
                if session.title is None:
                    t = clean_title(_user_text(msg))
                    if t:
                        session.title = t
                continue

            if role != "assistant":
                continue

            # Tool calls
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "toolCall":
                        tid = block.get("id") or f"tool_{len(tool_order)}"
                        args = block.get("arguments")
                        found_paths = paths_from_args(args, session.cwd, PATH_KEYS, CMD_KEYS)
                        if tid not in tools:
                            tools[tid] = set()
                            tool_order.append(tid)
                        tools[tid].update(found_paths)

            usage = msg.get("usage")
            if not isinstance(usage, dict):
                usage = obj.get("usage")
            if not isinstance(usage, dict):
                continue

            inp = int(usage.get("input") or 0)
            out = int(usage.get("output") or 0)
            cache_read = int(usage.get("cacheRead") or usage.get("cache_read") or 0)
            cache_write = int(usage.get("cacheWrite") or usage.get("cache_write") or 0)
            reasoning = int(usage.get("reasoning") or usage.get("reasoningTokens") or usage.get("reason") or 0)
            thinking = min(reasoning, out) if out else reasoning

            model = msg.get("model") or current_model or "unknown"
            mid = msg.get("responseId") or msg.get("id") or obj.get("id") or f"line_{idx}"
            key = f"{agent}:{session.id}:{mid}" if mid else None

            messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model=str(model),
                    input=inp,
                    output=out,
                    cache_read=cache_read,
                    cache_write=cache_write,
                    thinking=thinking,
                    cwd=session.cwd,
                    branch=session.branch,
                    key=key,
                )
            )

    session.messages = messages
    session.tool_paths = [unique(sorted(tools[t])) for t in tool_order if tools[t]]
    return session
