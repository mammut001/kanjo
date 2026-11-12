"""Kimi Code agent: ``~/.kimi-code`` and legacy ``~/.kimi``.

Sessions are recorded in ``sessions/<work_dir_hash>/<session_id>/wire.jsonl`` (protocol 1)
or ``sessions/<work_dir_hash>/<session_id>/agents/<agent>/wire.jsonl`` (protocol 1.5).
Workspace root (cwd) is resolved from ``state.json`` or the root ``kimi.json``.
"""

from __future__ import annotations

import glob
import hashlib
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

AGENT = "kimicode"


def roots() -> List[str]:
    explicit = (
        os.environ.get("KANJO_KIMICODE_DIR")
        or os.environ.get("TOKEI_KIMI_DIR")
        or os.environ.get("KIMI_CODE_HOME")
        or os.environ.get("KIMI_SHARE_DIR")
    )
    if explicit:
        return [winsupport.abspath(winsupport.expanduser(p)) for p in split_path_list(explicit) if p]
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    candidates = [
        winsupport.expanduser("~/.kimi-code"),
        winsupport.expanduser("~/.kimi"),
    ]
    existing = [winsupport.abspath(c) for c in candidates if os.path.exists(c)]
    return existing if existing else [winsupport.abspath(candidates[0])]


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(wire_jsonl_path, parent_session_id)]"""
    found: List[Tuple[str, Optional[str]]] = []
    seen: Set[str] = set()
    for root in dirs if dirs is not None else roots():
        sessions_dir = os.path.join(root, "sessions")
        if not os.path.isdir(sessions_dir):
            continue

        for session_dir in glob.glob(os.path.join(sessions_dir, "*", "*")):
            if not os.path.isdir(session_dir):
                continue
            # Root wire (protocol 1)
            root_wire = os.path.join(session_dir, "wire.jsonl")
            if os.path.isfile(root_wire):
                r_real = os.path.realpath(root_wire)
                if r_real not in seen:
                    seen.add(r_real)
                    found.append((root_wire, None))

            # Agent wires (protocol 1.5)
            for agent_wire in glob.glob(os.path.join(session_dir, "agents", "*", "wire.jsonl")):
                a_real = os.path.realpath(agent_wire)
                if a_real not in seen:
                    seen.add(a_real)
                    parent = os.path.basename(session_dir)
                    found.append((agent_wire, parent))
    return found


def _load_json(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _resolve_context(path: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Returns (session_id, cwd, subagent_of)."""
    parent_dir = os.path.dirname(path)
    # Check if this is under agents/<agent>/wire.jsonl
    grandparent = os.path.dirname(parent_dir)
    if os.path.basename(grandparent) == "agents":
        session_dir = os.path.dirname(grandparent)
        state = _load_json(os.path.join(session_dir, "state.json"))
        sid = state.get("id") or os.path.basename(session_dir)
        cwd = state.get("cwd")
        subagent = os.path.basename(session_dir)
        agent_name = os.path.basename(parent_dir)
        return f"{sid}_{agent_name}", cwd, subagent

    # Protocol 1: session_dir/wire.jsonl
    session_dir = parent_dir
    state = _load_json(os.path.join(session_dir, "state.json"))
    sid = state.get("id") or os.path.basename(session_dir)
    cwd = state.get("cwd")
    if not cwd:
        # Check root kimi.json
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(session_dir)))
        kimi_json = _load_json(os.path.join(root_dir, "kimi.json"))
        work_dir_hash = os.path.basename(os.path.dirname(session_dir))
        for item in kimi_json.get("work_dirs", []):
            if isinstance(item, dict):
                p = item.get("path")
                if isinstance(p, str) and p:
                    digest = hashlib.md5(p.encode("utf-8")).hexdigest()
                    kaos = item.get("kaos")
                    if digest == work_dir_hash or f"{kaos}_{digest}" == work_dir_hash:
                        cwd = p
                        break
    return str(sid), cwd, None


def _token(val: Any) -> int:
    try:
        return max(int(val or 0), 0)
    except (TypeError, ValueError):
        return 0


def _parse_ts(val: Any) -> Optional[float]:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        sec = float(val) / 1000.0 if val > 100_000_000_000 else float(val)
        return sec
    if isinstance(val, str):
        val_str = val.strip()
        if val_str.isdigit():
            num = int(val_str)
            return float(num) / 1000.0 if num > 100_000_000_000 else float(num)
        return parse_iso(val_str)
    return None


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    sid, cwd, parent_id = _resolve_context(path)
    actual_parent = subagent_of or parent_id
    session = Session(id=sid, agent=AGENT, file=path, subagent_of=actual_parent)
    if cwd:
        session.note_cwd(winsupport.abspath(winsupport.expanduser(cwd)))

    messages: List[Message] = []
    seen_events: Set[Tuple] = set()

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
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(rec, dict):
                continue

            # Protocol 1.5 usage.record
            if rec.get("type") == "usage.record":
                usage = rec.get("usage")
                if not isinstance(usage, dict):
                    continue
                inp = _token(usage.get("inputOther"))
                out = _token(usage.get("output"))
                cr = _token(usage.get("inputCacheRead"))
                cw = _token(usage.get("inputCacheCreation"))
                if inp + out + cr + cw == 0:
                    continue
                ts = _parse_ts(rec.get("time"))
                if ts:
                    session.note_time(ts)
                    if session.origin_ts is None:
                        session.origin_ts = ts
                model = str(rec.get("model") or "moonshot/kimi-k3")
                dedup_key = ("u", round((ts or 0.0) * 1000), model, inp, out, cr, cw)
                if dedup_key in seen_events:
                    continue
                seen_events.add(dedup_key)

                messages.append(
                    Message(
                        ts=ts or session.origin_ts or 0.0,
                        model=model,
                        input=inp,
                        output=out,
                        cache_read=cr,
                        cache_write=cw,
                        cwd=session.cwd,
                        key=f"{AGENT}:{session.id}:{line_no}",
                    )
                )
                continue

            # Protocol 1 StatusUpdate / SubagentEvent
            msg = rec.get("message")
            if isinstance(msg, dict):
                events_to_process = []
                m_type = msg.get("type")
                if m_type == "StatusUpdate":
                    events_to_process.append(msg.get("payload"))
                elif m_type == "SubagentEvent":
                    payload = msg.get("payload") or {}
                    ev = payload.get("event") or {}
                    if ev.get("type") == "StatusUpdate":
                        events_to_process.append(ev.get("payload"))

                for payload in events_to_process:
                    if not isinstance(payload, dict):
                        continue
                    usage = payload.get("token_usage")
                    if not isinstance(usage, dict):
                        continue
                    inp = _token(usage.get("input_other"))
                    out = _token(usage.get("output"))
                    cr = _token(usage.get("input_cache_read"))
                    cw = _token(usage.get("input_cache_creation"))
                    if inp + out + cr + cw == 0:
                        continue
                    mid = payload.get("message_id")
                    ts = _parse_ts(rec.get("timestamp"))
                    if ts:
                        session.note_time(ts)
                        if session.origin_ts is None:
                            session.origin_ts = ts
                    dedup_key = ("m", mid) if mid else ("t", round((ts or 0.0) * 1000), inp, out, cr, cw)
                    if dedup_key in seen_events:
                        continue
                    seen_events.add(dedup_key)

                    messages.append(
                        Message(
                            ts=ts or session.origin_ts or 0.0,
                            model="moonshot/kimi-k3",
                            input=inp,
                            output=out,
                            cache_read=cr,
                            cache_write=cw,
                            cwd=session.cwd,
                            key=f"{AGENT}:{session.id}:{mid or line_no}",
                        )
                    )

    session.messages = messages
    if actual_parent:
        session.id = f"{actual_parent}/{session.id}"
    return session
