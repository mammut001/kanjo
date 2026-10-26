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

from .base import Message, ParseError, Session, env_dirs, parse_iso, short_title

AGENT = "grok"


def roots() -> List[str]:
    explicit = os.environ.get("KANJO_GROK_DIR")
    if explicit:
        paths = []
        for p in explicit.split(os.pathsep):
            exp = os.path.expanduser(p)
            if os.path.isdir(exp) and os.path.basename(exp) != "sessions" and os.path.isdir(os.path.join(exp, "sessions")):
                paths.append(os.path.join(exp, "sessions"))
            else:
                paths.append(exp)
        return paths
    if os.environ.get("KANJO_DATA_DIR"):
        return []
    return [os.path.expanduser("~/.grok/sessions")]


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

    for turn in turns:
        if not isinstance(turn, dict):
            continue
        ts = parse_iso(turn.get("endedAt"))
        session.note_time(ts)
        turn_num = turn.get("turnNumber", len(session.messages))
        model_usage = turn.get("modelUsage")
        if isinstance(model_usage, dict) and model_usage:
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
                )
            )

    return session
