"""Qoder CLI: ``~/.qoder/projects/<project>/<session>.jsonl``
and Qoder CN: ``~/.qoder-cn/projects/<project>/<session>.jsonl``.

Agent transcripts record user and assistant turns with token usage.
Streaming responses sharing a request_id are merged to avoid double counting.
Legacy desktop transcript mirrors (paths containing /transcript/) are excluded.
"""

from __future__ import annotations

import glob
import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from ..identity import ScratchpadDecoder
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

AGENT = "qodercli"
PATH_KEYS = {
    "file_path", "path", "notebook_path", "filepath", "directory", "dir", "cwd",
    "workdir", "paths", "target_file", "absolute_path"
}
CMD_KEYS = {"command", "cmd"}


def roots(agent: str = "qodercli") -> List[str]:
    if agent == "qodercli_cn":
        env_val = os.environ.get("KANJO_QODERCLI_CN_DIR") or os.environ.get("TOKEI_QODERCLI_CN_DIR")
        default = "~/.qoder-cn/projects"
    else:
        env_val = os.environ.get("KANJO_QODERCLI_DIR") or os.environ.get("TOKEI_QODERCLI_DIR")
        default = "~/.qoder/projects"

    if env_val:
        return [winsupport.abspath(winsupport.expanduser(p)) for p in split_path_list(env_val) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    return [winsupport.abspath(winsupport.expanduser(default))]


def discover(dirs: Optional[List[str]] = None, agent: str = "qodercli") -> List[Tuple[str, Optional[str]]]:
    """[(file_path, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    search_roots = dirs if dirs is not None else roots(agent=agent)
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        candidates = (
            glob.glob(os.path.join(root, "*", "*.jsonl"))
            + glob.glob(os.path.join(root, "*", "*", "subagents", "*.jsonl"))
        )
        if not candidates:
            candidates = glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)

        for path in sorted(candidates):
            # Exclude legacy desktop transcript mirrors
            if f"{os.sep}transcript{os.sep}" in path:
                continue
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            parent = None
            if f"{os.sep}subagents{os.sep}" in path:
                parent = os.path.basename(os.path.dirname(os.path.dirname(path)))
            found.append((path, parent))
    return found


def _safe_int(val: Any) -> int:
    try:
        return max(int(val or 0), 0)
    except (TypeError, ValueError):
        return 0


def _parse_ts(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        sec = float(val) / 1000.0 if val > 10_000_000_000 else float(val)
        return sec
    if isinstance(val, str):
        val_str = val.strip()
        if val_str.isdigit():
            num = int(val_str)
            return float(num) / 1000.0 if num > 10_000_000_000 else float(num)
        return parse_iso(val_str)
    return None


def parse_file(path: str, subagent_of: Optional[str] = None, agent: str = "qodercli") -> Session:
    stem = os.path.splitext(os.path.basename(path))[0]
    actual_agent = "qodercli_cn" if (".qoder-cn" in path or agent == "qodercli_cn") else "qodercli"
    session = Session(id=stem, agent=actual_agent, file=path, subagent_of=subagent_of)

    tools: Dict[str, Set[str]] = {}
    tool_order: List[str] = []
    configured_model: Optional[str] = None
    user_first_text: Optional[str] = None

    # event_id -> dict with usage & metadata
    events: Dict[str, dict] = {}
    event_order: List[str] = []

    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ParseError(str(exc))

    with handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(row, dict):
                continue

            typ = row.get("type")
            if typ == "runtime-config":
                cfg_m = row.get("model")
                if cfg_m:
                    configured_model = str(cfg_m)
                cwd = row.get("cwd") or row.get("workspace")
                if isinstance(cwd, str) and cwd:
                    session.note_cwd(cwd)
                continue

            ts = _parse_ts(row.get("timestamp"))
            if ts is not None:
                if session.origin_ts is None:
                    session.origin_ts = ts
                session.note_time(ts)

            cwd = row.get("cwd")
            if isinstance(cwd, str) and cwd:
                session.note_cwd(cwd)

            message = row.get("message") if isinstance(row.get("message"), dict) else {}
            content = message.get("content")

            # Extract user title
            if typ == "user" and user_first_text is None:
                if isinstance(content, str) and content.strip():
                    user_first_text = content.strip()
                elif isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict) and b.get("type") == "text":
                            t = b.get("text")
                            if isinstance(t, str) and t.strip():
                                user_first_text = t.strip()
                                break

            if typ == "assistant":
                usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
                raw_in = _safe_int(usage.get("input_tokens"))
                cr = _safe_int(usage.get("cache_read_input_tokens"))
                if "cache_creation_input_tokens" in usage:
                    cw = _safe_int(usage.get("cache_creation_input_tokens"))
                else:
                    cache_creation = usage.get("cache_creation") or {}
                    cw = sum(_safe_int(cache_creation.get(k)) for k in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"))
                out = _safe_int(usage.get("output_tokens"))
                inp = max(raw_in - cr - cw, 0)
                model = message.get("model") or configured_model or "unknown"

                # Tool use blocks
                if isinstance(content, list):
                    for idx, block in enumerate(content):
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tid = str(block.get("id") or f"tool_{line_no}_{idx}")
                            found = paths_from_args(block.get("input"), session.cwd, PATH_KEYS, CMD_KEYS)
                            if tid not in tools:
                                tools[tid] = set()
                                tool_order.append(tid)
                            tools[tid].update(found)

                # Deduplication key by request_id or message_id
                req_id = usage.get("request_id") or message.get("id") or row.get("uuid") or row.get("id") or f"line_{line_no}"
                req_key = str(req_id)

                candidate = {
                    "ts": ts or session.origin_ts or 0.0,
                    "model": str(model),
                    "input": inp,
                    "output": out,
                    "cache_read": cr,
                    "cache_write": cw,
                    "total": inp + out + cr + cw,
                }

                if req_key not in events:
                    events[req_key] = candidate
                    event_order.append(req_key)
                else:
                    # Merge candidate keeping higher token count or richer metadata
                    existing = events[req_key]
                    if candidate["total"] >= existing["total"]:
                        events[req_key] = candidate

    if user_first_text:
        session.title = clean_title(user_first_text)

    # Fallback CWD: decode directory name if not yet recorded
    if session.cwd is None:
        parent_dir = os.path.basename(os.path.dirname(path))
        if f"{os.sep}subagents{os.sep}" in path:
            parent_dir = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(path))))
        decoded = ScratchpadDecoder().decode(parent_dir)
        if decoded:
            session.note_cwd(decoded)

    messages: List[Message] = []
    for k in event_order:
        ev = events[k]
        messages.append(
            Message(
                ts=ev["ts"],
                model=ev["model"],
                input=ev["input"],
                output=ev["output"],
                cache_read=ev["cache_read"],
                cache_write=ev["cache_write"],
                cwd=session.cwd,
                key=f"{session.agent}:{session.id}:{k}",
            )
        )

    session.messages = messages
    session.tool_paths = [unique(sorted(tools[t])) for t in tool_order if tools[t]]
    if subagent_of:
        session.id = f"{subagent_of}/{session.id}"
    return session
