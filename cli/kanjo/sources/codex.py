"""Codex CLI / Codex Desktop: ``~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`` and
``~/.codex/archived_sessions/rollout-*.jsonl``.

Each line is ``{"timestamp", "type", "payload"}``. Billing comes from
``event_msg/token_count`` (``info.last_token_usage`` per response;
``input_tokens`` includes ``cached_input_tokens``, ``output_tokens`` includes
``reasoning_output_tokens``). The model and cwd come from the latest
``turn_context``.

Forked and sub-agent rollouts replay their parent's history, including old
``token_count`` events. Each event carries the thread's cumulative
``total_token_usage``, so ``(total, last)`` identifies a response globally and
replays are dropped by the export's global de-duplication.
"""

from __future__ import annotations

import glob
import json
import os
import re
from typing import List, Optional, Tuple

from .base import Message, ParseError, Session, absolutize, env_dirs, extract_paths, paths_from_args, parse_iso, short_title, unique

AGENT = "codex"
PATH_KEYS = {"workdir", "path", "file_path", "cwd", "paths", "dir", "directory", "working_directory"}
CMD_KEYS = {"cmd", "command"}
_PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.M)
_MARKERS = (
    b'"token_count"', b'"function_call"', b'"custom_tool_call"', b'"local_shell_call"',
    b'"turn_context"', b'"session_meta"', b'"user_message"',
    b'"role": "user"', b'"role":"user"', b'"instructions"', b'"instruction"',
)
_FAST_HEADER = re.compile(
    rb'^\{"timestamp"\s*:\s*"([^"]+)"(?:\s*,\s*"ordinal"\s*:\s*\d+)?\s*,\s*"type"\s*:\s*"(\w+)"\s*,\s*"payload"\s*:\s*\{"type"\s*:\s*"(\w+)"'
)
_TRIGGER_FAST = {
    (b"response_item", b"function_call_output"),
    (b"response_item", b"custom_tool_call_output"),
    (b"event_msg", b"task_started"),
}
_OUTPUT_ITEM = re.compile(rb'"item"\s*:\s*\{\s*"type"\s*:\s*"(Reasoning|AgentMessage)"')
_ITEM_STARTED = re.compile(rb'"started_at_ms"\s*:\s*(\d+)')


def roots() -> List[str]:
    return env_dirs("KANJO_CODEX_DIR", ["~/.codex/sessions", "~/.codex/archived_sessions"])


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    found = []
    seen = set()
    for root in dirs if dirs is not None else roots():
        if not os.path.isdir(root):
            continue
        for path in sorted(glob.glob(os.path.join(root, "**", "rollout-*.jsonl"), recursive=True)):
            real = os.path.realpath(path)
            if real not in seen:
                seen.add(real)
                found.append((path, None))
    return found


def _usage_key(info) -> Optional[str]:
    total = info.get("total_token_usage")
    last = info.get("last_token_usage")
    if not isinstance(last, dict):
        return None
    return "codex:" + json.dumps([total, last], sort_keys=True, separators=(",", ":"))


def _tool_paths(payload, cwd) -> List[str]:
    kind = payload.get("type")
    name = payload.get("name") or ""
    if kind == "function_call":
        try:
            args = json.loads(payload.get("arguments") or "{}")
        except (TypeError, ValueError):
            return extract_paths(payload.get("arguments") or "")
        if isinstance(args, dict):
            work = args.get("workdir") if isinstance(args.get("workdir"), str) else cwd
            return paths_from_args(args, work, PATH_KEYS, CMD_KEYS)
        return []
    if kind == "custom_tool_call":
        text = payload.get("input")
        if not isinstance(text, str):
            return []
        if name == "apply_patch" or text.lstrip().startswith("*** Begin Patch"):
            out = []
            for m in _PATCH_FILE.finditer(text):
                p = absolutize(m.group(1) or m.group(2), cwd)
                if p:
                    out.append(p)
            return out
        if name in ("exec", "exec_command", "shell"):
            return extract_paths(text)
        return []
    if kind == "local_shell_call":
        action = payload.get("action") or {}
        if isinstance(action, dict):
            return paths_from_args(action, action.get("working_directory") or cwd, PATH_KEYS, CMD_KEYS)
    return []


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    stem = os.path.splitext(os.path.basename(path))[0]
    session = Session(id=stem, agent=AGENT, file=path)
    have_meta = False
    cwd = None
    model = "unknown"
    branch = None
    perf_trigger: Optional[int] = None
    perf_first: Optional[int] = None
    good = bad = 0
    try:
        handle = open(path, "rb")
    except OSError as exc:
        raise ParseError(str(exc))
    with handle:
        for raw in handle:
            head = raw[:512]
            matched = False
            for marker in _MARKERS:
                if marker in head:
                    matched = True
                    break
            if not matched:
                if b'"function_call_output"' in head or b'"custom_tool_call_output"' in head or b'"task_started"' in head:
                    fast = _FAST_HEADER.match(head)
                    if fast and (fast.group(2), fast.group(3)) in _TRIGGER_FAST:
                        t = parse_iso(fast.group(1).decode("ascii", "replace"))
                        if t is not None:
                            perf_trigger = int(round(t * 1000))
                            perf_first = None
                        continue
                    if len(raw) <= 4096:
                        matched = True
                elif b'"item_completed"' in head or (len(raw) <= 4096 and b'"item_completed"' in raw):
                    fast = _FAST_HEADER.match(head)
                    if fast and fast.group(3) == b"item_completed":
                        if _OUTPUT_ITEM.search(raw[:1024]):
                            ms_m = _ITEM_STARTED.search(raw[-512:] if len(raw) > 512 else raw)
                            if ms_m:
                                sms = int(ms_m.group(1))
                                if (perf_trigger is None or sms >= perf_trigger) and (
                                        perf_first is None or sms < perf_first):
                                    perf_first = sms
                        continue
                    if len(raw) <= 4096:
                        matched = True
            if not matched:
                if good == 0 and bad == 0 and raw.strip():
                    try:
                        json.loads(raw)
                        good += 1
                    except ValueError:
                        bad += 1
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
            payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
            ts = parse_iso(obj.get("timestamp"))
            if kind == "session_meta":
                if not have_meta:
                    have_meta = True
                    session.id = payload.get("id") or payload.get("session_id") or stem
                    cwd = payload.get("cwd") or cwd
                    session.note_cwd(cwd, 0)
                    source = payload.get("source")
                    parent = payload.get("parent_thread_id")
                    if not parent and isinstance(source, dict):
                        spawn = (source.get("subagent") or {}).get("thread_spawn") if isinstance(source.get("subagent"), dict) else None
                        if isinstance(spawn, dict):
                            parent = spawn.get("parent_thread_id")
                    if parent and parent != session.id:
                        session.subagent_of = parent
                    git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
                    branch = git.get("branch") or None
                    if git.get("repository_url") and cwd:
                        session.remote_hints[cwd] = git["repository_url"]
                    session.origin_ts = parse_iso(payload.get("timestamp")) or ts
                    session.note_time(session.origin_ts)
                continue
            if kind == "turn_context":
                cwd = payload.get("cwd") or cwd
                model = payload.get("model") or model
                session.note_cwd(cwd, 0)
                continue
            if kind == "event_msg":
                ptype = payload.get("type")
                if ptype == "user_message":
                    if session.title is None:
                        text = payload.get("message")
                        if isinstance(text, str):
                            t = short_title(text)
                            if t:
                                session.title = t
                    session.note_time(ts)
                    if ts is not None:
                        perf_trigger = int(round(ts * 1000))
                        perf_first = None
                elif ptype == "task_started":
                    if ts is not None:
                        perf_trigger = int(round(ts * 1000))
                        perf_first = None
                elif ptype == "item_completed":
                    item = payload.get("item")
                    if isinstance(item, dict) and item.get("type") in ("Reasoning", "AgentMessage"):
                        started_ms = item.get("started_at_ms")
                        if isinstance(started_ms, (int, float)) and not isinstance(started_ms, bool):
                            sms = int(started_ms)
                            if (perf_trigger is None or sms >= perf_trigger) and (
                                    perf_first is None or sms < perf_first):
                                perf_first = sms
                elif ptype == "token_count":
                    info = payload.get("info")
                    if not isinstance(info, dict) or ts is None:
                        continue
                    last = info.get("last_token_usage") or {}
                    inp = int(last.get("input_tokens") or 0)
                    cached = int(last.get("cached_input_tokens") or 0)
                    out = int(last.get("output_tokens") or 0)
                    reasoning = int(last.get("reasoning_output_tokens") or 0)
                    if not (inp or out or cached):
                        continue
                    end_ms = ts * 1000.0
                    gen_s = ttft_s = None
                    if perf_first is not None and end_ms > perf_first:
                        gen_s = round((end_ms - perf_first) / 1000.0, 3)
                        if perf_trigger is not None and perf_first >= perf_trigger:
                            ttft_s = round((perf_first - perf_trigger) / 1000.0, 3)
                    elif perf_trigger is not None and end_ms > perf_trigger:
                        gen_s = round((end_ms - perf_trigger) / 1000.0, 3)
                    session.messages.append(Message(
                        ts=ts, model=model, input=max(inp - cached, 0), output=out,
                        cache_read=min(cached, inp) if inp else cached,
                        thinking=min(reasoning, out) if out else reasoning,
                        cwd=cwd, branch=branch, key=_usage_key(info),
                        gen_s=gen_s, ttft_s=ttft_s))
                    perf_trigger = perf_first = None
                    session.note_time(ts)
                    session.note_cwd(cwd)
                continue
            if kind == "response_item":
                if payload.get("type") in ("function_call_output", "custom_tool_call_output"):
                    if ts is not None:
                        perf_trigger = int(round(ts * 1000))
                        perf_first = None
                    continue
                if session.title is None and payload.get("role") == "user":
                    content = payload.get("content")
                    text = None
                    if isinstance(content, list):
                        parts = []
                        for b in content:
                            if isinstance(b, dict):
                                t = b.get("text") or b.get("input_text")
                                if isinstance(t, str):
                                    parts.append(t)
                            elif isinstance(b, str):
                                parts.append(b)
                        if parts:
                            text = "\n".join(parts)
                    elif isinstance(content, str):
                        text = content
                    elif isinstance(payload.get("message"), str):
                        text = payload.get("message")
                    if text:
                        t = short_title(text)
                        if t:
                            session.title = t
                    session.note_time(ts)
                found = unique(_tool_paths(payload, cwd))
                if found:
                    session.tool_paths.append(found)
                continue
            if kind in ("instructions", "instruction"):
                if session.title is None:
                    text = payload.get("text") or payload.get("instructions") or payload.get("instruction")
                    if isinstance(text, str):
                        t = short_title(text)
                        if t:
                            session.title = t
                session.note_time(ts)
                continue
    if not have_meta:
        if good == 0 and bad > 0:
            raise ParseError("no valid JSON lines")
        if good > 0 or bad > 0:
            raise ParseError("no session_meta record")
    session.branch = branch
    return session
