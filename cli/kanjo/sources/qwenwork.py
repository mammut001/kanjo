"""QwenWork coding agent: ``~/.qwenworkcn/logs/sessions/<encoded dir>/<session uuid>/segments/*.jsonl``.

Each session is a directory representing a session UUID, containing sequential segment
files under ``segments/*.jsonl`` (read in filename order).

Lines are structured events:
``{"type", "ts", "seq", "turn_id", "loop_id", "request_id", "data": {...}}``.

Token usage is recorded on ``type == "model.response.completed"`` with fields:
``input_tokens``, ``output_tokens``, ``cache_read_input_tokens``, ``cache_creation_input_tokens``.
Model name is obtained from the event or the matching ``model.request.started`` event
(e.g. ``qmodel_latest``, ``qwork-advanced``). Working directory is captured from ``data.cwd``
(or ``data.project_root`` / ``data.target_dir``), which often resides under the QwenWork
sandbox (``~/.qwenworkcn/workspace/``) and correctly maps to the unattributed bucket if
not located in a tracked repository. Title is taken from the first ``input.prompt.submitted``
event via ``clean_title``. Duplicate messages are deduplicated by ``request_id``.

Token Mapping Decision:
In QwenWork / OpenAI-compatible completion events, ``input_tokens`` represents the total
prompt tokens, already inclusive of ``cache_read_input_tokens`` (and cache creation tokens).
Under Kanjo's ``Message`` contract, ``input`` must represent strictly non-cached input tokens,
while ``cache_read`` carries the cached tokens. To prevent double-counting, non-cached input
is mapped as ``max(0, input_tokens - cache_read_input_tokens - cache_creation_input_tokens)``.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional, Set, Tuple

from .base import (
    Message,
    ParseError,
    Session,
    clean_title,
    parse_iso,
    paths_from_args,
    unique,
)

AGENT = "qwenwork"

PATH_KEYS = {
    "file_path", "path", "notebook_path", "filepath", "directory", "dir", "cwd",
    "workdir", "paths", "target_file", "absolute_path", "target",
}
CMD_KEYS = {"command", "cmd"}


def roots() -> List[str]:
    explicit = os.environ.get("KANJO_QWENWORK_DIR") or os.environ.get("TOKEI_QWENWORK_HOME")
    default_dir = "~/.qwenworkcn/logs/sessions"
    if explicit:
        paths = []
        for p in explicit.split(os.pathsep):
            exp = os.path.expanduser(p)
            if os.path.isdir(os.path.join(exp, "logs", "sessions")):
                paths.append(os.path.join(exp, "logs", "sessions"))
            elif os.path.isdir(os.path.join(exp, "sessions")):
                paths.append(os.path.join(exp, "sessions"))
            else:
                paths.append(exp)
        return paths
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    return [os.path.expanduser(default_dir)]


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(session_dir, parent session id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    search_roots = dirs if dirs is not None else roots()

    for root in search_roots:
        if not os.path.isdir(root):
            continue

        # Look for segment directories under root/<encoded-dir>/<session-uuid>/segments
        # or root/<session-uuid>/segments
        candidates = (
            glob.glob(os.path.join(root, "*", "*", "segments"))
            + glob.glob(os.path.join(root, "*", "segments"))
        )
        if not candidates:
            candidates = [
                p for p in glob.glob(os.path.join(root, "**", "segments"), recursive=True)
                if os.path.isdir(p)
            ]

        for seg_dir in sorted(candidates):
            session_dir = os.path.dirname(seg_dir)
            real = os.path.realpath(session_dir)
            if real not in seen and glob.glob(os.path.join(seg_dir, "*.jsonl")):
                seen.add(real)
                found.append((session_dir, None))

        # Direct session dir support (e.g. root has segments/*.jsonl or is itself a session dir)
        if not found:
            direct_segs = os.path.join(root, "segments")
            if os.path.isdir(direct_segs) and glob.glob(os.path.join(direct_segs, "*.jsonl")):
                real = os.path.realpath(root)
                if real not in seen:
                    seen.add(real)
                    found.append((root, None))
            elif glob.glob(os.path.join(root, "*.jsonl")):
                real = os.path.realpath(root)
                if real not in seen:
                    seen.add(real)
                    found.append((root, None))

    return found


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    """Parse a QwenWork session from a session directory or segment file."""
    if os.path.isdir(path):
        if os.path.basename(path) == "segments":
            session_dir = os.path.dirname(path)
        else:
            session_dir = path
    else:
        parent = os.path.dirname(path)
        if os.path.basename(parent) == "segments":
            session_dir = os.path.dirname(parent)
        else:
            session_dir = parent

    sid = os.path.basename(session_dir)
    if not sid:
        sid = os.path.splitext(os.path.basename(path))[0]

    session = Session(id=sid, agent=AGENT, file=path, subagent_of=subagent_of)

    seg_dir = os.path.join(session_dir, "segments")
    if os.path.isdir(seg_dir):
        segment_files = sorted(glob.glob(os.path.join(seg_dir, "*.jsonl")))
    elif os.path.isdir(session_dir):
        segment_files = sorted(glob.glob(os.path.join(session_dir, "*.jsonl")))
    else:
        segment_files = []

    if not segment_files and os.path.isfile(path):
        segment_files = [path]

    seen_requests: Set[str] = set()
    pending_models: Dict[str, str] = {}
    tools: Dict[str, Set[str]] = {}
    tool_order: List[str] = []

    for seg_file in segment_files:
        try:
            handle = open(seg_file, "r", encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ParseError(f"Cannot read segment file {seg_file}: {exc}")

        with handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(obj, dict):
                    continue

                ev_type = obj.get("type")
                data = obj.get("data") if isinstance(obj.get("data"), dict) else {}

                ts = parse_iso(obj.get("ts"))
                if ts is not None:
                    if session.origin_ts is None:
                        session.origin_ts = ts
                    session.note_time(ts)

                # Working directory
                cwd = data.get("cwd") or data.get("project_root") or data.get("target_dir")
                if cwd and isinstance(cwd, str):
                    session.note_cwd(cwd)

                # Title from first input.prompt.submitted
                if ev_type == "input.prompt.submitted" and not session.title:
                    preview = data.get("text_preview") or data.get("text") or data.get("prompt")
                    if preview and isinstance(preview, str):
                        cleaned = clean_title(preview)
                        if cleaned:
                            session.title = cleaned

                # Tool paths from tool.requested
                if ev_type == "tool.requested":
                    t_id = obj.get("tool_call_id") or str(len(tool_order))
                    if t_id not in tools:
                        tools[t_id] = set()
                        tool_order.append(t_id)
                    args = data.get("args")
                    if isinstance(args, dict):
                        found_paths = paths_from_args(args, session.cwd, PATH_KEYS, CMD_KEYS)
                        tools[t_id].update(found_paths)

                # Remember model from model.request.started
                if ev_type == "model.request.started":
                    req_id = obj.get("request_id")
                    m = data.get("model")
                    if req_id and m:
                        pending_models[req_id] = str(m)

                # Model response completed
                if ev_type == "model.response.completed":
                    req_id = obj.get("request_id")
                    if req_id:
                        if req_id in seen_requests:
                            continue
                        seen_requests.add(req_id)

                    model_name = data.get("model") or (pending_models.get(req_id) if req_id else None) or "qmodel_latest"
                    inp = max(int(data.get("input_tokens") or 0), 0)
                    out = max(int(data.get("output_tokens") or 0), 0)
                    cache_read = max(int(data.get("cache_read_input_tokens") or 0), 0)
                    cache_write = max(int(data.get("cache_creation_input_tokens") or 0), 0)

                    # Deduct cache reads and writes from input to avoid double-counting
                    non_cached_in = max(0, inp - cache_read - cache_write)
                    msg_key = f"qwenwork:{session.id}:{req_id}" if req_id else f"qwenwork:{session.id}:{len(session.messages)}"

                    session.messages.append(
                        Message(
                            ts=ts or session.origin_ts or 0.0,
                            model=str(model_name),
                            input=non_cached_in,
                            output=out,
                            cache_read=cache_read,
                            cache_write=cache_write,
                            thinking=0,
                            cwd=session.cwd,
                            branch=session.branch,
                            key=msg_key,
                        )
                    )

    session.tool_paths = [unique(sorted(tools[t])) for t in tool_order if tools[t]]
    return session
