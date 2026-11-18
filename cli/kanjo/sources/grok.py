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

Output speed (``Message.gen_s``): ``usage.json`` turns are timed from the
``shell.turn.inference_done`` records in ``~/.grok/logs/unified.jsonl``;
``turn_completed`` turns, and ``usage.json`` turns the log does not cover,
from each model's ``apiDurationMs``. Neither carries a
usable time to first token, so ``ttft_s`` stays unset.
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
                  turn_gen_s: Optional[float] = None, per_model_timing: bool = False,
                  same_turn: Optional[dict] = None) -> None:
    """Add the Messages for one turn's usage object (usage.json turn or turn_completed).

    ``turn_gen_s`` (usage.json turns, timed from logs/unified.jsonl) applies only
    when the turn used one model. ``per_model_timing`` (turn_completed) takes each
    model's own ``apiDurationMs``. ``same_turn`` is the turn_completed usage
    for this usage.json turn: a model left untimed by the unified log borrows its
    ``apiDurationMs`` when both report the same output tokens.
    """
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
        gen_s = _gen_s(u) if per_model_timing else (None if multi else turn_gen_s)
        if gen_s is None and same_turn is not None:
            other_models = same_turn.get("modelUsage")
            other = other_models.get(model_name) if isinstance(other_models, dict) and other_models else same_turn
            if isinstance(other, dict) and _int(other.get("outputTokens")) == _int(u.get("outputTokens")):
                gen_s = _gen_s(other)
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
                gen_s=gen_s,
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

    completed = _turn_completed(updates_path) if os.path.isfile(updates_path) else []

    def same_turn(end: Optional[float]) -> Optional[dict]:
        if end is None:
            return None
        for tc_ts, _tc_id, tc_usage in completed:
            if tc_ts is not None and abs(tc_ts - end) <= _SAME_TURN_S:
                return tc_usage
        return None

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
                if ts is not None:
                    usage_ends.append(ts)
                turn_num = turn.get("turnNumber", len(session.messages))
                _append_usage(
                    session, turn, turn.get("primaryModelId") or "grok",
                    ts or session.origin_ts or 0.0,
                    f"grok:{session.id}:{turn_num}", cwd, branch,
                    turn_gen_s=round(elapsed_ms / 1000.0, 3) if elapsed_ms > 0 else None,
                    same_turn=same_turn(ts),
                )

    # --- updates.jsonl turn_completed (all builds) ---
    if completed:
        for ts, turn_id, usage in completed:
            if ts is not None and any(abs(ts - end) <= _SAME_TURN_S for end in usage_ends):
                continue  # already counted from usage.json
            if not _has_tokens(usage):
                continue
            session.note_time(ts)
            _append_usage(
                session, usage, current_model,
                ts or session.origin_ts or 0.0,
                f"grok:{session.id}:p:{turn_id}", cwd, branch, per_model_timing=True,
            )

    return session
