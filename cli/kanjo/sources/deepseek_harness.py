"""DeepSeek Harness: ``~/.tokei/cache/dsh-sessions/**/*.jsonl``.

Each JSONL file contains a harness session.
Lines contain event objects with event types:
- ``session``: contains ``id`` and ``cwd``.
- ``request/header``: contains current model / provider configuration.
- ``assistant/chunk`` (priority 1) and ``assistant/message`` (priority 2):
  contain usage metrics (``inputTokens``, ``outputTokens``, ``cacheReadTokens``,
  ``cacheWriteTokens``, ``reasoningTokens``). For each (turn, step), the final
  message takes precedence over partial usage chunks.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from .base import (
    Message,
    ParseError,
    Session,
    clean_title,
    env_dirs,
    unique,
)

AGENT = "deepseek_harness"


def roots() -> List[str]:
    explicit = (
        os.environ.get("KANJO_DEEPSEEK_HARNESS_DIR")
        or os.environ.get("TOKEI_DSH_DECOMPRESSED_DIR")
    )
    if explicit:
        return [os.path.abspath(os.path.expanduser(p)) for p in explicit.split(os.pathsep) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    return [os.path.abspath(os.path.expanduser("~/.tokei/cache/dsh-sessions"))]


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(jsonl_path, parent session id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    for root in dirs if dirs is not None else roots():
        if not os.path.isdir(root):
            continue
        candidates = (
            glob.glob(os.path.join(root, "*.jsonl"))
            + glob.glob(os.path.join(root, "*", "*.jsonl"))
            + glob.glob(os.path.join(root, "**", "*.jsonl"), recursive=True)
        )
        for path in sorted(candidates):
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                found.append((path, None))
    return found


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    stem = os.path.splitext(os.path.basename(path))[0]
    session = Session(id=stem, agent=AGENT, file=path, subagent_of=subagent_of)

    try:
        handle = open(path, "r", encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise ParseError(str(exc))

    current_model = "deepseek-v4-pro"
    current_provider = "deepseek-official"
    candidates: Dict[Tuple[int, int], dict] = {}
    title_candidate: Optional[str] = None

    with handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line or '"type"' not in line:
                continue
            try:
                item = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(item, dict):
                continue

            event_type = item.get("type")

            if event_type == "session":
                sid = item.get("id")
                if sid:
                    session.id = str(sid)
                cwd = item.get("cwd")
                if isinstance(cwd, str) and cwd:
                    session.note_cwd(cwd)
                created_at = item.get("createdAt") or item.get("time")
                if created_at:
                    try:
                        ts = float(created_at) / 1000.0 if float(created_at) > 1e11 else float(created_at)
                        session.origin_ts = ts
                        session.note_time(ts)
                    except (ValueError, TypeError):
                        pass
                continue

            if event_type == "request/header":
                data = item.get("data")
                if isinstance(data, dict):
                    header = data.get("header")
                    if isinstance(header, dict):
                        config = header.get("config")
                        if isinstance(config, dict):
                            if config.get("model"):
                                current_model = str(config["model"])
                            if config.get("provider"):
                                current_provider = str(config["provider"])
                continue

            if event_type == "user/message":
                if title_candidate is None:
                    data = item.get("data")
                    if isinstance(data, dict):
                        text = data.get("text") or (data.get("message") or {}).get("content")
                        if isinstance(text, str) and text.strip():
                            title_candidate = clean_title(text.strip())
                continue

            data = item.get("data") or {}
            if not isinstance(data, dict):
                continue

            priority = 0
            usage = None
            msg_model = current_model

            if event_type == "assistant/message":
                usage = data.get("usage")
                message = data.get("message") or {}
                if isinstance(message, dict):
                    source = message.get("source") or {}
                    if isinstance(source, dict):
                        replay = source.get("replayState") or source.get("replay_state") or {}
                        resp = replay.get("response") if isinstance(replay, dict) else None
                        served = (resp.get("responseModel") or resp.get("response_model")) if isinstance(resp, dict) else None
                        if served:
                            msg_model = str(served)
                        elif source.get("model"):
                            msg_model = str(source["model"])
                priority = 2
            elif event_type == "assistant/chunk":
                chunk = data.get("chunk") or {}
                if isinstance(chunk, dict) and chunk.get("type") == "usage":
                    usage = chunk.get("usage")
                    priority = 1

            if not isinstance(usage, dict) or priority == 0:
                continue

            try:
                turn = int(data.get("turn", 0))
                step = int(data.get("step", 0))
            except (ValueError, TypeError):
                continue

            raw_time = item.get("time") or item.get("timestamp")
            ts = None
            if raw_time is not None:
                try:
                    ts = float(raw_time) / 1000.0 if float(raw_time) > 1e11 else float(raw_time)
                except (ValueError, TypeError):
                    ts = None

            inp = max(int(usage.get("inputTokens") or usage.get("input") or 0), 0)
            out = max(int(usage.get("outputTokens") or usage.get("output") or 0), 0)
            cr = max(int(usage.get("cacheReadTokens") or usage.get("cacheRead") or 0), 0)
            cw = max(int(usage.get("cacheWriteTokens") or usage.get("cacheWrite") or 0), 0)
            reason = max(int(usage.get("reasoningTokens") or usage.get("reasoning") or 0), 0)
            thinking = min(reason, out) if out else reason

            if inp + out + cr + cw <= 0:
                continue

            key = (turn, step)
            prev = candidates.get(key)
            if prev is None or priority >= prev["priority"]:
                candidates[key] = {
                    "priority": priority,
                    "ts": ts or session.origin_ts or 0.0,
                    "turn": turn,
                    "step": step,
                    "model": msg_model,
                    "input": inp,
                    "output": out,
                    "cache_read": cr,
                    "cache_write": cw,
                    "thinking": thinking,
                }

    if title_candidate:
        session.title = title_candidate

    # Sort messages by (ts, turn, step)
    sorted_items = sorted(candidates.values(), key=lambda c: (c["ts"], c["turn"], c["step"]))
    for item in sorted_items:
        session.note_time(item["ts"])
        session.messages.append(
            Message(
                ts=item["ts"],
                model=item["model"],
                input=item["input"],
                output=item["output"],
                cache_read=item["cache_read"],
                cache_write=item["cache_write"],
                thinking=item["thinking"],
                cwd=session.cwd,
                key=f"{AGENT}:{session.id}:{item['turn']}:{item['step']}",
            )
        )

    return session
