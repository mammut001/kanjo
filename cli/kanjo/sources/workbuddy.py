"""WorkBuddy coding agent: ``~/.workbuddy/projects/<slug>/<session>.jsonl``
and WorkBuddy AI (Intl): ``~/.workbuddy-ai/projects/<slug>/<session>.jsonl``.

Each JSONL file contains an interactive session or sub-task.
Lines contain events: message turns, providerData with usage metrics, function calls,
ai-title, and working directory (cwd).
"""

from __future__ import annotations

import glob
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from ..identity import ScratchpadDecoder
from .base import (
    Message,
    ParseError,
    Session,
    clean_title,
    env_dirs,
    parse_iso,
    paths_from_args,
    unique,
)

AGENT = "workbuddy"
PATH_KEYS = {
    "file_path", "path", "notebook_path", "filepath", "directory", "dir", "cwd",
    "workdir", "paths", "target_file", "absolute_path"
}
CMD_KEYS = {"command", "cmd"}


def roots(agent: str = "workbuddy") -> List[str]:
    if agent == "workbuddy_ai":
        env_val = os.environ.get("KANJO_WORKBUDDY_AI_DIR") or os.environ.get("WORKBUDDY_AI_DIR")
        default = "~/.workbuddy-ai/projects"
    elif agent == "codebuddy":
        env_val = os.environ.get("KANJO_CODEBUDDY_DIR") or os.environ.get("TOKEI_CODEBUDDY_DIR") or os.environ.get("CODEBUDDY_DIR")
        default = "~/.codebuddy/projects"
    else:
        env_val = os.environ.get("KANJO_WORKBUDDY_DIR") or os.environ.get("WORKBUDDY_DIR")
        default = "~/.workbuddy/projects"

    if env_val:
        return [os.path.abspath(os.path.expanduser(p)) for p in env_val.split(os.pathsep) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    return [os.path.abspath(os.path.expanduser(default))]


def discover(dirs: Optional[List[str]] = None, agent: str = "workbuddy") -> List[Tuple[str, Optional[str]]]:
    """[(file_path, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    search_roots = dirs if dirs is not None else roots(agent=agent)
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        candidates = glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)
        for path in sorted(candidates):
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                found.append((path, None))
    return found


def _number(obj: Any, *keys: str) -> Optional[int]:
    if not isinstance(obj, dict):
        return None
    for k in keys:
        if k in obj:
            val = obj.get(k)
            if isinstance(val, bool):
                continue
            try:
                return max(int(val), 0)
            except (TypeError, ValueError):
                continue
    return None


def _detail_total(value: Any, *keys: str) -> int:
    if isinstance(value, dict):
        return _number(value, *keys) or 0
    if isinstance(value, list):
        return sum(_number(item, *keys) or 0 for item in value if isinstance(item, dict))
    return 0


def _parse_ts(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        sec = float(value) / 1000.0 if value > 10_000_000_000 else float(value)
        return sec
    if isinstance(value, str):
        val_str = value.strip()
        if val_str.isdigit():
            num = int(val_str)
            return float(num) / 1000.0 if num > 10_000_000_000 else float(num)
        return parse_iso(val_str)
    return None


def _extract_usage(item: dict) -> Optional[Dict[str, Any]]:
    message = item.get("message") if isinstance(item.get("message"), dict) else {}
    provider = item.get("providerData") if isinstance(item.get("providerData"), dict) else {}
    if not provider and isinstance(message.get("providerData"), dict):
        provider = message.get("providerData")

    item_usage = item.get("usage") if isinstance(item.get("usage"), dict) else {}
    message_usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
    normalized = provider.get("usage") if isinstance(provider.get("usage"), dict) else {}
    raw = provider.get("rawUsage") if isinstance(provider.get("rawUsage"), dict) else {}
    sources = [x for x in (item_usage, message_usage, normalized, raw) if isinstance(x, dict) and x]

    input_total = output = 0
    selected = None
    for source in sources:
        inp = _number(source, "input_tokens", "inputTokens", "input", "prompt_tokens")
        out = _number(source, "output_tokens", "outputTokens", "output", "completion_tokens")
        if (inp or 0) + (out or 0) > 0:
            selected = source
            input_total = inp or 0
            output = out or 0
            break

    if selected is None:
        return None

    cache_reads = []
    cache_writes = []
    totals = []
    for source in sources:
        cache_reads.extend([
            _number(source, "cache_read_input_tokens", "cacheReadInputTokens",
                    "cache_read", "cacheRead", "cached_tokens", "cachedTokens") or 0,
            _number(source, "prompt_cache_hit_tokens") or 0,
            _detail_total(source.get("inputTokensDetails"), "cached_tokens", "cachedTokens"),
            _detail_total(source.get("input_tokens_details"), "cached_tokens", "cachedTokens"),
            _detail_total(source.get("prompt_tokens_details"), "cached_tokens", "cachedTokens"),
        ])
        cache_writes.extend([
            _number(source, "cache_creation_input_tokens", "cacheCreationInputTokens",
                    "cache_write_input_tokens", "cacheWriteInputTokens",
                    "prompt_cache_write_tokens", "cache_write", "cacheWrite") or 0,
        ])
        tot = _number(source, "total_tokens", "totalTokens", "total")
        if tot is not None:
            totals.append(tot)

    cache_read = max(cache_reads, default=0)
    cache_write = max(cache_writes, default=0)

    # If total_tokens equals input_total + output, input_total includes cache_read/cache_write
    inclusive = any(tot == input_total + output for tot in totals)
    if inclusive:
        cache_read = min(cache_read, input_total)
        cache_write = min(cache_write, max(input_total - cache_read, 0))
        input_tokens = max(input_total - cache_read - cache_write, 0)
    else:
        input_tokens = max(input_total - cache_read - cache_write, 0) if (cache_read + cache_write > 0 and input_total >= cache_read + cache_write) else input_total

    thinking = (
        _number(raw, "completion_thinking_tokens", "thinking")
        or _detail_total(raw.get("completion_tokens_details"), "reasoning_tokens")
        or _detail_total(normalized.get("outputTokensDetails"), "reasoning_tokens")
        or _number(item_usage, "thinking", "reasoning_tokens")
        or 0
    )
    if output:
        thinking = min(thinking, output)

    model = (
        provider.get("requestModelName")
        or provider.get("requestModelId")
        or provider.get("model")
        or message.get("model")
        or item.get("model")
        or "unknown"
    )
    message_id = provider.get("messageId") or item.get("messageId") or item.get("id") or ""

    return {
        "input": input_tokens,
        "output": output,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "thinking": thinking,
        "model": str(model),
        "message_id": str(message_id),
    }


def parse_file(path: str, subagent_of: Optional[str] = None, agent: str = "workbuddy") -> Session:
    stem = os.path.splitext(os.path.basename(path))[0]
    if ".codebuddy" in path or agent == "codebuddy":
        actual_agent = "codebuddy"
    elif ".workbuddy-ai" in path or agent == "workbuddy_ai":
        actual_agent = "workbuddy_ai"
    else:
        actual_agent = "workbuddy"
    session = Session(id=stem, agent=actual_agent, file=path, subagent_of=subagent_of)

    tools: Dict[str, Set[str]] = {}
    tool_order: List[str] = []
    messages: List[Message] = []
    user_first_text: Optional[str] = None
    ai_title: Optional[str] = None

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
                item = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(item, dict):
                continue

            ts = _parse_ts(item.get("timestamp") or (item.get("message") or {}).get("timestamp"))
            if ts is not None:
                if session.origin_ts is None:
                    session.origin_ts = ts
                session.note_time(ts)

            cwd = item.get("cwd")
            if isinstance(cwd, str) and cwd:
                session.note_cwd(cwd)

            sid = item.get("sessionId")
            if isinstance(sid, str) and sid:
                session.id = sid

            t = (
                item.get("aiTitle")
                or item.get("title")
                or (item.get("message") if isinstance(item.get("message"), dict) else {}).get("aiTitle")
            )
            if t:
                ai_title = str(t)

            item_type = item.get("type")

            # Extract user prompt for title fallback
            if user_first_text is None:
                role = item.get("role") or (item_type if item_type == "user" else None)
                if role == "user":
                    content = item.get("content") or item.get("rawContent")
                    if not content and isinstance(item.get("message"), dict):
                        content = item["message"].get("content")
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("text"):
                                user_first_text = str(part["text"]).strip()
                                break
                    elif isinstance(content, str) and content.strip():
                        user_first_text = content.strip()

            # Tool call path tracking
            if item_type == "function_call":
                fn_name = item.get("name") or "tool"
                call_id = str(item.get("callId") or f"{fn_name}_{line_no}")
                args = item.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                found = paths_from_args(args, session.cwd, PATH_KEYS, CMD_KEYS)
                if call_id not in tools:
                    tools[call_id] = set()
                    tool_order.append(call_id)
                tools[call_id].update(found)
            elif isinstance(item.get("tool_calls"), list):
                for tc in item["tool_calls"]:
                    if isinstance(tc, dict):
                        args = tc.get("arguments")
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}
                        found = paths_from_args(args, session.cwd, PATH_KEYS, CMD_KEYS)
                        call_id = tc.get("id") or tc.get("name") or f"tool_{line_no}"
                        if call_id not in tools:
                            tools[call_id] = set()
                            tool_order.append(call_id)
                        tools[call_id].update(found)

            # Usage recording
            usage = _extract_usage(item)
            if usage is not None:
                mid = usage["message_id"]
                m_ts = ts or session.origin_ts or 0.0
                key = f"{session.agent}:{session.id}:{mid}" if mid else f"{session.agent}:{session.id}:{line_no}"
                m = Message(
                    ts=m_ts,
                    model=usage["model"],
                    input=usage["input"],
                    output=usage["output"],
                    cache_read=usage["cache_read"],
                    cache_write=usage["cache_write"],
                    thinking=usage.get("thinking", 0),
                    cwd=session.cwd,
                    key=key,
                )
                messages.append(m)

    # Title resolution
    if ai_title:
        session.title = clean_title(ai_title)
    elif user_first_text:
        session.title = clean_title(user_first_text)

    # Fallback CWD from directory name if not found in log
    if session.cwd is None:
        parent_dir = os.path.basename(os.path.dirname(path))
        decoded = ScratchpadDecoder().decode(parent_dir)
        if decoded:
            session.note_cwd(decoded)

    session.messages = messages
    session.tool_paths = [unique(sorted(tools[t])) for t in tool_order if tools[t]]
    if subagent_of:
        session.id = f"{subagent_of}/{session.id}"
    return session
