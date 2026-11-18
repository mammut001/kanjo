"""Claude Code: ``~/.claude/projects/<slug>/<session>.jsonl`` and sub-agents in
``~/.claude/projects/<slug>/<session>/subagents/*.jsonl``.

Streaming writes one line per content block, all carrying the same
``message.id`` and the same ``usage``; the last line of a message id wins
(ATTRIBUTION.md section 7). Tool calls are collected from every line, since
each line holds a different block.
"""

from __future__ import annotations

import glob
import json
import os
import re
from typing import Dict, List, Optional, Set, Tuple

from .base import Message, ParseError, Session, env_dirs, paths_from_args, parse_iso, short_title, unique

AGENT = "claude"
PATH_KEYS = {"file_path", "path", "notebook_path", "filepath", "directory", "dir", "cwd",
             "workdir", "paths", "target_file", "absolute_path"}
CMD_KEYS = {"command", "cmd"}
_TS = re.compile(rb'"timestamp"\s*:\s*"([^"]+)"')
_LINE_TIME = re.compile(rb'"uuid"\s*:\s*"([^"]+)"\s*,\s*"timestamp"\s*:\s*"([^"]+)"')
_ATTACHMENT_LINE = re.compile(rb'"type"\s*:\s*"attachment"\s*,\s*"uuid"\s*:\s*"([^"]+)"')
_LINE_PARENT = re.compile(rb'"parentUuid"\s*:\s*"([^"]+)"')


def _note_line_time(raw: bytes, when: Dict[str, float], via: Dict[str, Optional[str]]) -> None:
    if b'"uuid"' not in raw:
        return
    head = raw[:2048]
    att = _ATTACHMENT_LINE.search(head)
    if att:
        uid = att.group(1).decode("utf-8", "replace")
        par = _LINE_PARENT.search(head)
        via[uid] = par.group(1).decode("utf-8", "replace") if par else None
        return
    m = _LINE_TIME.search(head)
    if m:
        ts = parse_iso(m.group(2).decode("ascii", "replace"))
        if ts is not None:
            when[m.group(1).decode("utf-8", "replace")] = ts
        return
    if len(raw) <= 8192:
        try:
            obj = json.loads(raw)
        except ValueError:
            return
        if not isinstance(obj, dict):
            return
        uid = obj.get("uuid")
        if not isinstance(uid, str):
            return
        if obj.get("type") == "attachment":
            par = obj.get("parentUuid")
            via[uid] = par if isinstance(par, str) else None
        else:
            ts = parse_iso(obj.get("timestamp"))
            if ts is not None:
                when[uid] = ts


def _request_start(parent: Optional[str], when: Dict[str, float],
                   via: Dict[str, Optional[str]]) -> Optional[float]:
    for _ in range(64):
        if parent is None:
            return None
        if parent in when:
            return when[parent]
        if parent not in via:
            return None
        parent = via[parent]
    return None


def roots() -> List[str]:
    return env_dirs("KANJO_CLAUDE_DIR", ["~/.claude/projects"])


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(file, parent session id for sub-agents)]"""
    found = []
    for root in dirs if dirs is not None else roots():
        if not os.path.isdir(root):
            continue
        for path in sorted(glob.glob(os.path.join(root, "*", "*.jsonl"))):
            found.append((path, None))
        for path in sorted(glob.glob(os.path.join(root, "*", "*", "subagents", "*.jsonl"))):
            parent = os.path.basename(os.path.dirname(os.path.dirname(path)))
            found.append((path, parent))
    return found


def _user_text(message) -> Optional[str]:
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = None
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                break
            if isinstance(block, dict) and block.get("type") == "tool_result":
                return None
    else:
        return None
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped or stripped.startswith("Caveat:"):
        return None
    if stripped.startswith(("<local-command-caveat", "<local-command-stdout", "<task-notification")):
        return None
    m_cmd = re.search(r"<command-args>(.*?)</command-args>", stripped, re.DOTALL)
    if m_cmd and m_cmd.group(1).strip():
        return m_cmd.group(1).strip()
    return stripped


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    stem = os.path.splitext(os.path.basename(path))[0]
    session = Session(id=stem, agent=AGENT, file=path, subagent_of=subagent_of)
    messages: Dict[str, Message] = {}
    order: List[str] = []
    tools: Dict[str, Set[str]] = {}
    tool_order: List[str] = []
    branches: Dict[str, int] = {}
    when: Dict[str, float] = {}
    via: Dict[str, Optional[str]] = {}
    req_events: Dict[str, List[Tuple[float, Optional[str], object, str]]] = {}
    good = bad = 0
    try:
        handle = open(path, "rb")
    except OSError as exc:
        raise ParseError(str(exc))
    with handle:
        for raw in handle:
            if session.origin_ts is None:
                m_ts = _TS.search(raw[:4096])
                if m_ts:
                    session.origin_ts = parse_iso(m_ts.group(1).decode("ascii", "replace"))
            is_assistant = b'"assistant"' in raw
            want_user = session.title is None and b'"user"' in raw
            want_custom = b'"custom-title"' in raw
            if not is_assistant and not want_user and not want_custom:
                if good == 0 and bad == 0 and raw.strip():
                    # still validate that the file is JSON lines at all
                    try:
                        json.loads(raw)
                        good += 1
                    except ValueError:
                        bad += 1
                _note_line_time(raw, when, via)
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                bad += 1
                continue
            if not isinstance(obj, dict):
                bad += 1
                continue
            good += 1
            kind = obj.get("type")
            ts = parse_iso(obj.get("timestamp"))
            uid = obj.get("uuid")
            if kind == "attachment":
                if isinstance(uid, str):
                    par = obj.get("parentUuid")
                    via[uid] = par if isinstance(par, str) else None
                continue
            if isinstance(uid, str) and ts is not None:
                when[uid] = ts
            cwd = obj.get("cwd") if isinstance(obj.get("cwd"), str) else None
            if kind == "custom-title":
                ct = obj.get("customTitle")
                if isinstance(ct, str):
                    t = short_title(ct)
                    if t:
                        session.title = t
                continue
            if kind == "user":
                if not obj.get("isMeta"):
                    raw_text = _user_text(obj.get("message"))
                    if raw_text:
                        if "This session is being continued from a previous conversation that ran out of context" in raw_text:
                            if session.title is None:
                                summary_title = short_title(raw_text)
                                if summary_title:
                                    session.title = summary_title
                        elif session.title is None:
                            t = short_title(raw_text)
                            if t:
                                session.title = t
                session.note_time(ts)
                session.note_cwd(cwd, 0)
                continue
            if kind != "assistant":
                continue
            msg = obj.get("message") or {}
            if not isinstance(msg, dict):
                continue
            session.note_time(ts)
            branch = obj.get("gitBranch") or None
            # tool calls: content blocks plus the wire-level inputs (which keep
            # the real "cd /abs/path && ..." prefix the transcript strips)
            content = msg.get("content")
            wire = obj.get("wireToolInputs") if isinstance(obj.get("wireToolInputs"), dict) else {}
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    tid = block.get("id") or "%s:%d" % (obj.get("uuid"), len(tool_order))
                    found = paths_from_args(block.get("input"), cwd, PATH_KEYS, CMD_KEYS)
                    found += paths_from_args(wire.get(tid), cwd, PATH_KEYS, CMD_KEYS)
                    if tid not in tools:
                        tools[tid] = set()
                        tool_order.append(tid)
                    tools[tid].update(found)
            usage = msg.get("usage")
            if not isinstance(usage, dict) or ts is None:
                continue
            mid = msg.get("id") or obj.get("uuid")
            details = usage.get("output_tokens_details") or {}
            cache = usage.get("cache_creation") or {}
            m = Message(
                ts=ts,
                model=msg.get("model") or "unknown",
                input=int(usage.get("input_tokens") or 0),
                output=int(usage.get("output_tokens") or 0),
                cache_read=int(usage.get("cache_read_input_tokens") or 0),
                cache_write=int(usage.get("cache_creation_input_tokens") or 0),
                cache_write_1h=int(cache.get("ephemeral_1h_input_tokens") or 0) if isinstance(cache, dict) else 0,
                thinking=int(details.get("thinking_tokens") or 0) if isinstance(details, dict) else 0,
                cwd=cwd,
                branch=branch,
                key="claude:%s" % mid if mid else None,
            )
            k = mid or "line:%d" % len(order)
            if k not in messages:
                order.append(k)
            messages[k] = m  # last line of a message id wins
            request_id = obj.get("requestId") or obj.get("request_id")
            req_key = request_id or mid or k
            req_events.setdefault(req_key, []).append(
                (ts, obj.get("parentUuid"), obj.get("thinkingDurationMs"), k)
            )
            if cwd:
                session.note_cwd(cwd)
            if branch:
                branches[branch] = branches.get(branch, 0) + 1
            if obj.get("sessionId") and subagent_of is None:
                session.id = obj["sessionId"]
    if good == 0 and bad > 0:
        raise ParseError("no valid JSON lines")
    for group in req_events.values():
        end = max(ev_ts for ev_ts, _, _, _ in group)
        first = None
        for ev_ts, _, think_ms, _ in group:
            if think_ms:
                try:
                    tms = float(think_ms)
                except (TypeError, ValueError):
                    continue
                if tms > 0:
                    first = ev_ts - tms / 1000.0
                    break
        start = _request_start(group[0][1], when, via)
        gen = ttft = None
        if first is not None and end > first:
            gen = end - first
            if start is not None and first >= start:
                ttft = first - start
        elif start is not None and end > start:
            gen = end - start
        if gen:
            gen_s = round(gen, 3)
            ttft_s = round(ttft, 3) if ttft is not None else None
            for _, _, _, k in group:
                m = messages.get(k)
                if m is not None:
                    m.gen_s = gen_s
                    m.ttft_s = ttft_s
    session.messages = [messages[k] for k in order]
    session.tool_paths = [unique(sorted(tools[t])) for t in tool_order if tools[t]]
    if branches:
        session.branch = max(branches.items(), key=lambda kv: kv[1])[0]
    if subagent_of:
        session.id = "%s/%s" % (subagent_of, stem)
    return session
