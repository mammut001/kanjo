"""Muse Code agent: ``~/.local/share/muse/sessions/**/session.jsonl``.

Extracts token usage, models, and sessions from the event-stream JSONL logs.
Subagents live under ``.../<parent_session>/subagent/<child_session>/session.jsonl``.
Workspace root (cwd) is resolved from ``runtime.session.metadata``.
"""

from __future__ import annotations

import glob
import json
import math
import os
from typing import Any, Dict, List, Optional, Set, Tuple

from .. import winsupport
from .base import (
    Message,
    ParseError,
    Session,
    clean_title,
    env_dirs,
    parse_iso,
    unique,
    split_path_list,
)

AGENT = "musecode"


def roots() -> List[str]:
    explicit = os.environ.get("KANJO_MUSECODE_DIR") or os.environ.get("TOKEI_MUSE_DIR")
    if explicit:
        return [winsupport.abspath(winsupport.expanduser(p)) for p in split_path_list(explicit) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    # XDG data dir on POSIX, %LOCALAPPDATA%\muse on Windows.
    return [winsupport.abspath(winsupport.local_data_dir("muse"))]


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(session_jsonl_path, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    for root in dirs if dirs is not None else roots():
        sessions_dir = os.path.join(root, "sessions")
        if not os.path.isdir(sessions_dir):
            continue
        candidates = glob.glob(os.path.join(sessions_dir, "**", "session.jsonl"), recursive=True)
        for path in sorted(candidates):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            parent = None
            parts = winsupport.path_parts(path)
            if "subagent" in parts:
                idx = parts.index("subagent")
                if idx > 0:
                    parent = parts[idx - 1]
            found.append((path, parent))
    return found


def _number(val: Any) -> int:
    try:
        return max(int(val or 0), 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _parse_ts(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        f = float(val)
        if not math.isfinite(f):
            return None
        if f > 100_000_000_000_000:
            return f / 1_000_000.0
        if f > 100_000_000_000:
            return f / 1000.0
        return f
    if isinstance(val, str):
        val_str = val.strip()
        if val_str.isdigit():
            num = int(val_str)
            return float(num) / 1000.0 if num > 100_000_000_000 else float(num)
        return parse_iso(val_str)
    return None


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    parent_id = subagent_of
    parts = winsupport.path_parts(path)
    if not parent_id and "subagent" in parts:
        idx = parts.index("subagent")
        if idx > 0:
            parent_id = parts[idx - 1]

    session_dir = os.path.dirname(path)
    sid = os.path.basename(session_dir)
    session = Session(id=sid, agent=AGENT, file=path, subagent_of=parent_id)

    run_models: Dict[str, str] = {}
    seen_records: Set[str] = set()
    messages: List[Message] = []
    branches: Dict[str, int] = {}

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
                record = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(record, dict):
                continue

            stream = record.get("stream")
            if isinstance(stream, dict):
                stream_id = stream.get("id")
                if stream_id and isinstance(stream_id, str):
                    session.id = stream_id

            ts = _parse_ts(record.get("recorded_at") or record.get("timestamp"))
            if ts:
                session.note_time(ts)
                if session.origin_ts is None:
                    session.origin_ts = ts

            payload_type = record.get("payload_type")
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}

            if payload_type == "runtime.session.metadata":
                meta = payload.get("record") if isinstance(payload.get("record"), dict) else {}
                workspace = meta.get("workspace_root")
                if isinstance(workspace, str) and workspace:
                    session.note_cwd(winsupport.abspath(workspace))
                continue

            if payload_type == "session.workspace_branch.observed":
                branch = payload.get("branch")
                if isinstance(branch, str) and branch.strip():
                    b_name = branch.strip()
                    branches[b_name] = branches.get(b_name, 0) + 1
                continue

            if payload_type == "session.name.changed":
                new_name = payload.get("new_name")
                if isinstance(new_name, str) and new_name.strip():
                    session.title = clean_title(new_name.strip())
                continue

            if payload_type == "run.model.configured":
                meta = payload.get("record") if isinstance(payload.get("record"), dict) else {}
                run_stream = meta.get("run_stream")
                model_id = meta.get("model_id")
                if (isinstance(run_stream, dict) and isinstance(model_id, str)
                        and model_id and model_id != "same-as-main"):
                    run_id = run_stream.get("id")
                    if isinstance(run_id, str) and run_id:
                        run_models[run_id] = model_id
                continue

            if payload_type != "runtime.session" or payload.get("kind") != "run":
                continue

            event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
            if event.get("kind") != "model_completed":
                continue

            usage = event.get("usage") if isinstance(event.get("usage"), dict) else {}
            input_total = _number(usage.get("input_tokens"))
            cached = _number(usage.get("cached_tokens") or usage.get("cache_read_tokens"))
            cached = min(cached, input_total)
            inp = max(0, input_total - cached)
            out = _number(usage.get("output_tokens"))
            cw = _number(usage.get("cache_write_tokens"))
            reason = _number(usage.get("reasoning_tokens"))

            if inp + out + cached + cw + reason == 0:
                continue

            rec_id = record.get("source_run_record_id")
            if isinstance(rec_id, str) and rec_id:
                if rec_id in seen_records:
                    continue
                seen_records.add(rec_id)

            model = event.get("model")
            if not isinstance(model, str) or not model or model == "same-as-main":
                model = run_models.get(str(payload.get("run_id") or ""), "")
            if not model:
                model = "muse-spark-1.2"

            thinking = min(reason, out) if out else reason
            mid = rec_id or f"msg_{line_no}"
            messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model=str(model),
                    input=inp,
                    output=out,
                    cache_read=cached,
                    cache_write=cw,
                    thinking=thinking,
                    cwd=session.cwd,
                    key=f"{AGENT}:{session.id}:{mid}",
                )
            )

    session.messages = messages
    if branches:
        session.branch = max(branches.items(), key=lambda kv: kv[1])[0]
    if parent_id:
        session.id = f"{parent_id}/{session.id}"
    return session
