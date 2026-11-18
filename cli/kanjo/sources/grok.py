"""Grok CLI: ``~/.grok/sessions/<cwd>/<session_id>/{summary.json,usage.json}``.

Each session directory has metadata in ``summary.json`` and per-turn billing in
``usage.json``. Each turn in ``turns[]`` carries token usage and ``modelUsage``
breakdowns. Working directory, git branch, and git remotes are read from
``summary.json``. Subagent sessions have ``session_kind: subagent`` (or
``parent_session_id``).
"""

from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional, Tuple

from .. import winsupport
from .base import Message, ParseError, Session, env_dirs, parse_iso, short_title, split_path_list

AGENT = "grok"
_UNIFIED_CACHE: Dict[str, Tuple[tuple, Dict[str, List[Tuple[float, float]]]]] = {}


def _find_unified_log(session_dir: str) -> Optional[str]:
    cur = os.path.abspath(session_dir)
    for _ in range(4):
        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            break
        cand = os.path.join(parent, "logs", "unified.jsonl")
        if os.path.isfile(cand):
            return cand
        cur = parent
    return None


def _unified_inference_by_sid(log_path: str) -> Dict[str, List[Tuple[float, float]]]:
    try:
        st = os.stat(log_path)
    except OSError:
        return {}
    real_path = os.path.realpath(log_path)
    sig = (st.st_ino, st.st_mtime_ns, st.st_size)
    cached = _UNIFIED_CACHE.get(real_path)
    if cached is not None and cached[0] == sig:
        return cached[1]

    by_sid: Dict[str, List[Tuple[float, float]]] = {}
    seen = set()
    try:
        with open(real_path, "rb") as fh:
            for raw in fh:
                if b"shell.turn.inference_done" not in raw:
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(obj, dict) or obj.get("msg") != "shell.turn.inference_done":
                    continue
                ctx = obj.get("ctx")
                if not isinstance(ctx, dict):
                    continue
                sid = str(obj.get("sid") or "")
                ts_str = str(obj.get("ts") or "")
                ts = parse_iso(ts_str)
                if not sid or ts is None:
                    continue
                try:
                    prompt = max(int(ctx.get("prompt_tokens") or 0), 0)
                    cached_tok = max(int(ctx.get("cached_prompt_tokens") or 0), 0)
                    completion = max(int(ctx.get("completion_tokens") or 0), 0)
                    reasoning = max(int(ctx.get("reasoning_tokens") or 0), 0)
                    loop_index = int(ctx.get("loop_index") or 0)
                    attempts = int(ctx.get("attempts") or 0)
                except (TypeError, ValueError, OverflowError):
                    continue
                cached_tok = min(cached_tok, prompt)
                reasoning = min(reasoning, completion)
                record_id = f"{sid}:{ts_str}:{loop_index}:{attempts}:{prompt}:{cached_tok}:{completion}:{reasoning}"
                if record_id in seen:
                    continue
                seen.add(record_id)
                elapsed = ctx.get("model_elapsed_ms")
                if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) and elapsed > 0:
                    by_sid.setdefault(sid, []).append((ts, float(elapsed)))
    except OSError:
        return {}

    for recs in by_sid.values():
        recs.sort(key=lambda item: item[0])
    if len(_UNIFIED_CACHE) >= 4:
        _UNIFIED_CACHE.clear()
    _UNIFIED_CACHE[real_path] = (sig, by_sid)
    return by_sid


def _turn_elapsed_ms(turn_timestamps: List[Optional[float]],
                     inf_records: List[Tuple[float, float]]) -> Dict[int, float]:
    timed = sorted(
        ((i, t) for i, t in enumerate(turn_timestamps) if t is not None),
        key=lambda item: (item[1], item[0]),
    )
    if not timed or not inf_records:
        return {}
    out: Dict[int, float] = {}
    last = len(timed) - 1
    for rec_ts, elapsed_ms in inf_records:
        for pos, (turn_idx, turn_ts) in enumerate(timed):
            cutoff = turn_ts + 0.5 if pos == last else min(turn_ts + 0.5, (turn_ts + timed[pos + 1][1]) / 2.0)
            if rec_ts <= cutoff:
                out[turn_idx] = out.get(turn_idx, 0.0) + elapsed_ms
                break
    return out


def roots() -> List[str]:
    explicit = os.environ.get("KANJO_GROK_DIR")
    if explicit:
        paths = []
        for p in split_path_list(explicit):
            exp = winsupport.expanduser(p)
            if os.path.isdir(exp) and os.path.basename(exp) != "sessions" and os.path.isdir(os.path.join(exp, "sessions")):
                paths.append(os.path.join(exp, "sessions"))
            else:
                paths.append(exp)
        return paths
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    return [winsupport.expanduser("~/.grok/sessions")]


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(usage_json_path, parent session id for subagents)]"""
    found = []
    seen = set()
    for root in dirs if dirs is not None else roots():
        if not os.path.isdir(root):
            continue
        candidates = (
            glob.glob(os.path.join(root, "*", "*", "usage.json"))
            + glob.glob(os.path.join(root, "*", "usage.json"))
        )
        for path in sorted(candidates):
            real = os.path.realpath(path)
            if real in seen:
                continue
            seen.add(real)
            subagent_of = None
            sum_path = os.path.join(os.path.dirname(path), "summary.json")
            if os.path.isfile(sum_path):
                try:
                    with open(sum_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    pid = data.get("parent_session_id")
                    kind = data.get("session_kind")
                    if pid:
                        subagent_of = str(pid)
                    elif kind and "subagent" in str(kind):
                        subagent_of = "subagent"
                except (OSError, ValueError):
                    pass
            found.append((path, subagent_of))
    return found


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    if os.path.isdir(path):
        usage_path = os.path.join(path, "usage.json")
        summary_path = os.path.join(path, "summary.json")
    elif path.endswith("summary.json"):
        usage_path = os.path.join(os.path.dirname(path), "usage.json")
        summary_path = path
    else:
        usage_path = path
        summary_path = os.path.join(os.path.dirname(path), "summary.json")

    session_dir = os.path.dirname(usage_path)
    fallback_id = os.path.basename(session_dir)

    summary_data = {}
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as handle:
                summary_data = json.load(handle)
        except (OSError, ValueError):
            summary_data = {}

    info = summary_data.get("info") or {}
    sid = str(info.get("id") or fallback_id)
    cwd = info.get("cwd") or None
    branch = summary_data.get("head_branch") or None
    title = summary_data.get("generated_title") or summary_data.get("session_summary") or None
    created_at = summary_data.get("created_at")
    pid = summary_data.get("parent_session_id")
    kind = summary_data.get("session_kind")

    if subagent_of is None:
        if pid:
            subagent_of = str(pid)
        elif kind and "subagent" in str(kind):
            subagent_of = "subagent"

    session = Session(
        id=sid,
        agent=AGENT,
        file=path,
        subagent_of=subagent_of,
        title=short_title(title),
    )
    session.origin_ts = parse_iso(created_at)
    session.note_time(session.origin_ts)
    if cwd:
        session.note_cwd(cwd)
    if branch:
        session.branch = branch

    git_root = summary_data.get("git_root_dir")
    remotes = summary_data.get("git_remotes")
    if isinstance(remotes, list) and git_root:
        for r in remotes:
            if isinstance(r, str):
                session.remote_hints[git_root] = r

    if not os.path.isfile(usage_path):
        return session

    try:
        with open(usage_path, "r", encoding="utf-8") as handle:
            usage_data = json.load(handle)
    except OSError as exc:
        raise ParseError("cannot read usage.json: %s" % exc)
    except ValueError as exc:
        raise ParseError("invalid JSON in usage.json: %s" % exc)

    if not isinstance(usage_data, dict):
        raise ParseError("usage.json must be a JSON object")

    if usage_data.get("sessionId"):
        session.id = str(usage_data["sessionId"])

    turns = usage_data.get("turns") or []
    if not isinstance(turns, list):
        return session

    turn_timestamps = [
        parse_iso(turn.get("endedAt")) if isinstance(turn, dict) else None
        for turn in turns
    ]
    turn_ms: Dict[int, float] = {}
    unified_path = _find_unified_log(session_dir)
    if unified_path:
        inf_records = _unified_inference_by_sid(unified_path).get(session.id)
        if inf_records:
            turn_ms = _turn_elapsed_ms(turn_timestamps, inf_records)

    for idx, turn in enumerate(turns):
        if not isinstance(turn, dict):
            continue
        ts = turn_timestamps[idx]
        session.note_time(ts)
        elapsed_ms = turn_ms.get(idx, 0.0)
        gen_s = round(elapsed_ms / 1000.0, 3) if elapsed_ms > 0 else None
        turn_num = turn.get("turnNumber", len(session.messages))
        model_usage = turn.get("modelUsage")
        if isinstance(model_usage, dict) and model_usage:
            single_model = len(model_usage) == 1
            for model_name, u in model_usage.items():
                if not isinstance(u, dict):
                    continue
                inp = int(u.get("inputTokens") or 0)
                out = int(u.get("outputTokens") or 0)
                cache_r = int(u.get("cachedReadTokens") or 0)
                cache_w = int(u.get("cacheCreationTokens") or 0)
                thinking = int(u.get("reasoningTokens") or 0)
                non_cached_in = max(0, inp - cache_r)
                key = (
                    f"grok:{session.id}:{turn_num}:{model_name}"
                    if len(model_usage) > 1
                    else f"grok:{session.id}:{turn_num}"
                )
                session.messages.append(
                    Message(
                        ts=ts or session.origin_ts or 0.0,
                        model=str(model_name),
                        input=non_cached_in,
                        output=out,
                        cache_read=cache_r,
                        cache_write=cache_w,
                        thinking=thinking,
                        cwd=cwd,
                        branch=branch,
                        key=key,
                        gen_s=gen_s if single_model else None,
                    )
                )
        else:
            model_name = turn.get("primaryModelId") or "grok"
            inp = int(turn.get("inputTokens") or 0)
            out = int(turn.get("outputTokens") or 0)
            cache_r = int(turn.get("cachedReadTokens") or 0)
            cache_w = int(turn.get("cacheCreationTokens") or 0)
            thinking = int(turn.get("reasoningTokens") or 0)
            non_cached_in = max(0, inp - cache_r)
            key = f"grok:{session.id}:{turn_num}"
            session.messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model=str(model_name),
                    input=non_cached_in,
                    output=out,
                    cache_read=cache_r,
                    cache_write=cache_w,
                    thinking=thinking,
                    cwd=cwd,
                    branch=branch,
                    key=key,
                    gen_s=gen_s,
                )
            )

    return session
