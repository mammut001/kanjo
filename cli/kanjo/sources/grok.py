"""Grok CLI: ``~/.grok/sessions/<cwd>/<session_id>/``.

Each session directory has metadata in ``summary.json`` (working directory, git
branch, git remotes, ``current_model_id``). Subagent sessions have
``session_kind: subagent`` (or ``parent_session_id``).

Token usage comes from two files:

* ``usage.json`` (older Grok CLI builds): ``turns[]``, each with token counts
  and a ``modelUsage`` breakdown.
* ``updates.jsonl`` (all builds; the only one newer builds write): ACP-style
  ``session/update`` / ``_x.ai/session/update`` records. A
  ``turn_completed`` update carries the same per-turn ``usage`` object
  (token counts, ``modelUsage``, ``apiDurationMs``).

``usage.json`` turns are used exactly as before. A ``turn_completed`` record
adds a turn only when no ``usage.json`` turn ended at the same moment, so
sessions without ``usage.json``, and turns that ``usage.json`` dropped, are
counted once.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional, Tuple

from .. import winsupport
from .base import Message, ParseError, Session, env_dirs, parse_iso, short_title, split_path_list

AGENT = "grok"

# A turn_completed record and a usage.json turn describe the same turn when their
# end times are this close (seconds). Grok writes both at the same moment.
_SAME_TURN_S = 1.0

# Per-turn generation time needs Message.gen_s, which not every build has yet.
_HAS_GEN_S = "gen_s" in getattr(Message, "__dataclass_fields__", {})


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


def _session_file(session_dir: str) -> Optional[str]:
    """The file that changes whenever the session's usage does.

    ``updates.jsonl`` gets every new turn; ``usage.json`` alone only for
    sessions written before ``updates.jsonl`` existed.
    """
    for name in ("updates.jsonl", "usage.json"):
        path = os.path.join(session_dir, name)
        if os.path.isfile(path):
            return path
    return None


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(updates.jsonl or usage.json path, parent session id for subagents)]"""
    found = []
    seen = set()
    for root in dirs if dirs is not None else roots():
        if not os.path.isdir(root):
            continue
        session_dirs = set()
        for name in ("usage.json", "updates.jsonl"):
            for pattern in (os.path.join(root, "*", "*", name), os.path.join(root, "*", name)):
                session_dirs.update(os.path.dirname(p) for p in glob.glob(pattern))
        for session_dir in sorted(session_dirs):
            path = _session_file(session_dir)
            if path is None:
                continue
            real = os.path.realpath(session_dir)
            if real in seen:
                continue
            seen.add(real)
            subagent_of = None
            sum_path = os.path.join(session_dir, "summary.json")
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


def _int(value) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _gen_s(u: dict) -> Optional[float]:
    ms = u.get("apiDurationMs")
    if isinstance(ms, bool) or not isinstance(ms, (int, float)) or ms <= 0:
        return None
    if _int(u.get("outputTokens")) <= 0:
        return None
    return round(ms / 1000.0, 3)


def _append_usage(session: Session, usage: dict, fallback_model: str, ts: float,
                  key_base: str, cwd: Optional[str], branch: Optional[str],
                  timed: bool) -> None:
    """Add the Messages for one turn's usage object (usage.json turn or turn_completed)."""
    model_usage = usage.get("modelUsage")
    if isinstance(model_usage, dict) and model_usage:
        parts = [(str(name), u) for name, u in model_usage.items() if isinstance(u, dict)]
        multi = len(model_usage) > 1
        if not parts:
            return
    else:
        parts = [(str(fallback_model), usage)]
        multi = False
    for model_name, u in parts:
        inp = _int(u.get("inputTokens"))
        cache_r = _int(u.get("cachedReadTokens"))
        extra = {}
        if timed and _HAS_GEN_S:
            gen = _gen_s(u)
            if gen is not None:
                extra["gen_s"] = gen
        session.messages.append(
            Message(
                ts=ts,
                model=model_name,
                input=max(0, inp - cache_r),
                output=_int(u.get("outputTokens")),
                cache_read=cache_r,
                cache_write=_int(u.get("cacheCreationTokens")),
                thinking=_int(u.get("reasoningTokens")),
                cwd=cwd,
                branch=branch,
                key=f"{key_base}:{model_name}" if multi else key_base,
                **extra,
            )
        )


def _turn_completed(updates_path: str) -> List[Tuple[Optional[float], str, dict]]:
    """[(end time, turn id, usage)] from the ``turn_completed`` records in updates.jsonl."""
    out: List[Tuple[Optional[float], str, dict]] = []
    try:
        handle = open(updates_path, "rb")
    except OSError as exc:
        raise ParseError("cannot read updates.jsonl: %s" % exc)
    with handle:
        for raw in handle:
            if b'"turn_completed"' not in raw:
                continue
            try:
                obj = json.loads(raw)
            except ValueError:
                continue
            params = obj.get("params") if isinstance(obj, dict) else None
            update = params.get("update") if isinstance(params, dict) else None
            if not isinstance(update, dict) or update.get("sessionUpdate") != "turn_completed":
                continue
            usage = update.get("usage")
            if not isinstance(usage, dict):
                continue
            meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
            ts: Optional[float] = None
            ms = meta.get("agentTimestampMs")
            if isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms > 0:
                ts = ms / 1000.0
            else:
                sec = obj.get("timestamp")
                if isinstance(sec, (int, float)) and not isinstance(sec, bool) and sec > 0:
                    ts = float(sec)
            turn_id = str(update.get("prompt_id") or meta.get("eventId") or len(out))
            out.append((ts, turn_id, usage))
    return out


def _has_tokens(usage: dict) -> bool:
    keys = ("inputTokens", "outputTokens", "cachedReadTokens", "cacheCreationTokens", "reasoningTokens")
    if any(_int(usage.get(k)) for k in keys):
        return True
    model_usage = usage.get("modelUsage")
    if isinstance(model_usage, dict):
        return any(isinstance(u, dict) and any(_int(u.get(k)) for k in keys) for u in model_usage.values())
    return False


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    session_dir = path if os.path.isdir(path) else os.path.dirname(path)
    usage_path = os.path.join(session_dir, "usage.json")
    summary_path = os.path.join(session_dir, "summary.json")
    updates_path = os.path.join(session_dir, "updates.jsonl")
    fallback_id = os.path.basename(session_dir)

    summary_data = {}
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as handle:
                summary_data = json.load(handle)
        except (OSError, ValueError):
            summary_data = {}
    if not isinstance(summary_data, dict):
        summary_data = {}

    info = summary_data.get("info") or {}
    sid = str(info.get("id") or fallback_id)
    cwd = info.get("cwd") or None
    branch = summary_data.get("head_branch") or None
    title = summary_data.get("generated_title") or summary_data.get("session_summary") or None
    created_at = summary_data.get("created_at")
    pid = summary_data.get("parent_session_id")
    kind = summary_data.get("session_kind")
    current_model = summary_data.get("current_model_id") or "grok"

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

    # --- usage.json (older builds) ---
    usage_ends: List[float] = []
    if os.path.isfile(usage_path):
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
        if isinstance(turns, list):
            for turn in turns:
                if not isinstance(turn, dict):
                    continue
                ts = parse_iso(turn.get("endedAt"))
                session.note_time(ts)
                if ts is not None:
                    usage_ends.append(ts)
                turn_num = turn.get("turnNumber", len(session.messages))
                _append_usage(
                    session, turn, turn.get("primaryModelId") or "grok",
                    ts or session.origin_ts or 0.0,
                    f"grok:{session.id}:{turn_num}", cwd, branch, timed=False,
                )

    # --- updates.jsonl turn_completed (all builds) ---
    if os.path.isfile(updates_path):
        for ts, turn_id, usage in _turn_completed(updates_path):
            if ts is not None and any(abs(ts - end) <= _SAME_TURN_S for end in usage_ends):
                continue  # already counted from usage.json
            if not _has_tokens(usage):
                continue
            session.note_time(ts)
            _append_usage(
                session, usage, current_model,
                ts or session.origin_ts or 0.0,
                f"grok:{session.id}:p:{turn_id}", cwd, branch, timed=True,
            )

    return session
