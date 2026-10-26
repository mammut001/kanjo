"""Qwen Code: ``~/.qwen/usage/token-usage-YYYY-MM.jsonl`` and ``~/.qwen/projects/*/chats/<sessionId>.jsonl``.

Per-request token usage is logged to monthly JSONL files in ``usage/``.
Session working directories, git branches, and timestamps are recorded in
the per-session chat logs under ``projects/<slug>/chats/<sessionId>.jsonl``
(and ``usage_record.jsonl``).

File->Session Mapping and Cache Invalidation:
Because monthly usage files contain multiple sessions, each session is
identified and cached by its per-session chat file (``chats/<sessionId>.jsonl``).
This ensures:
1. One Session per sessionId is discovered and returned.
2. Changes to an active session invalidate only that session's cache entry
   in ``cache.py``, rather than invalidating the entire month of sessions.
3. Accurate repository and git branch attribution from per-message transcript
   headers.
"""

from __future__ import annotations

import glob
import json
import os
from typing import Dict, List, Optional, Set, Tuple

from .base import Message, ParseError, Session, env_dirs, parse_iso, short_title

AGENT = "qwen"

# In-memory cache for parsed token-usage files: (filepath, mtime_ns, size) -> [records]
_USAGE_CACHE: Dict[Tuple[str, int, int], List[dict]] = {}


def roots() -> List[str]:
    return env_dirs("KANJO_QWEN_DIR", ["~/.qwen"])


def _find_usage_files(root: str) -> List[str]:
    candidates = []
    # ~/.qwen/usage/token-usage-*.jsonl
    candidates.extend(glob.glob(os.path.join(root, "usage", "token-usage-*.jsonl")))
    # Direct token-usage-*.jsonl in root
    candidates.extend(glob.glob(os.path.join(root, "token-usage-*.jsonl")))
    # Any token-usage-*.jsonl recursively
    if not candidates:
        candidates.extend(glob.glob(os.path.join(root, "**", "token-usage-*.jsonl"), recursive=True))
    return sorted(set(candidates))


def _read_usage_records(path: str) -> List[dict]:
    try:
        st = os.stat(path)
    except OSError:
        return []
    key = (path, st.st_mtime_ns, st.st_size)
    if key in _USAGE_CACHE:
        return _USAGE_CACHE[key]
    records = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        return []
    _USAGE_CACHE[key] = records
    return records


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    """[(session_file_path, parent session id)]"""
    found = []
    seen = set()
    seen_sids = set()

    for root in dirs if dirs is not None else roots():
        if not os.path.isdir(root):
            continue

        # 1. Discover per-session chat transcript files
        chat_patterns = [
            os.path.join(root, "projects", "*", "chats", "*.jsonl"),
            os.path.join(root, "*", "chats", "*.jsonl"),
            os.path.join(root, "chats", "*.jsonl"),
        ]
        for pattern in chat_patterns:
            for path in sorted(glob.glob(pattern)):
                real = os.path.realpath(path)
                if real in seen:
                    continue
                seen.add(real)
                sid = os.path.splitext(os.path.basename(path))[0]
                seen_sids.add(sid)
                found.append((path, None))

        # 2. Check token-usage files for any session not having a chat file
        for u_path in _find_usage_files(root):
            for rec in _read_usage_records(u_path):
                sid = rec.get("sessionId")
                if sid and sid not in seen_sids:
                    seen_sids.add(sid)
                    # Check if a runtime.json file exists for this session
                    r_candidates = glob.glob(os.path.join(root, "projects", "*", "chats", f"{sid}.runtime.json"))
                    if r_candidates:
                        real = os.path.realpath(r_candidates[0])
                        if real not in seen:
                            seen.add(real)
                            found.append((r_candidates[0], None))
                    else:
                        real = os.path.realpath(u_path)
                        if real not in seen:
                            seen.add(real)
                            found.append((u_path, None))

    return found


def _locate_qwen_root(path: str) -> str:
    """Ascend from path until finding ~/.qwen or directory containing projects/usage."""
    cur = os.path.dirname(os.path.abspath(path))
    while cur and cur != "/":
        if os.path.isdir(os.path.join(cur, "usage")) or os.path.isdir(os.path.join(cur, "projects")):
            return cur
        cur = os.path.dirname(cur)
    explicit = os.environ.get("KANJO_QWEN_DIR")
    if explicit:
        return os.path.expanduser(explicit)
    return os.path.expanduser("~/.qwen")


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    root = _locate_qwen_root(path)
    base_name = os.path.basename(path)
    sid = os.path.splitext(base_name)[0]

    session = Session(id=sid, agent=AGENT, file=path, subagent_of=subagent_of)

    # 1. Parse chat transcript if this is a chat file or one exists
    chat_path = None
    if path.endswith(".jsonl") and not base_name.startswith("token-usage-"):
        chat_path = path
    else:
        candidates = glob.glob(os.path.join(root, "projects", "*", "chats", f"{sid}.jsonl"))
        if candidates:
            chat_path = candidates[0]

    branches: Dict[str, int] = {}
    if chat_path and os.path.isfile(chat_path):
        try:
            with open(chat_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    ts = parse_iso(obj.get("timestamp"))
                    if session.origin_ts is None and ts is not None:
                        session.origin_ts = ts
                    session.note_time(ts)

                    cwd = obj.get("cwd")
                    if isinstance(cwd, str) and cwd:
                        session.note_cwd(cwd)

                    branch = obj.get("gitBranch")
                    if isinstance(branch, str) and branch:
                        branches[branch] = branches.get(branch, 0) + 1

                    if session.title is None and obj.get("type") == "user":
                        msg = obj.get("message")
                        if isinstance(msg, dict):
                            parts = msg.get("parts")
                            if isinstance(parts, list):
                                for part in parts:
                                    if isinstance(part, dict) and part.get("text"):
                                        session.title = short_title(part.get("text"))
                                        break
        except OSError as exc:
            raise ParseError("cannot read chat transcript: %s" % exc)

    if branches:
        session.branch = max(branches.items(), key=lambda kv: kv[1])[0]

    # 2. Fallbacks for cwd and branch from runtime.json or usage_record.jsonl
    if session.cwd is None:
        runtime_files = glob.glob(os.path.join(root, "projects", "*", "chats", f"{sid}.runtime.json"))
        for rf in runtime_files:
            try:
                with open(rf, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                if isinstance(data, dict) and data.get("work_dir"):
                    session.note_cwd(data["work_dir"])
                    break
            except (OSError, ValueError):
                pass

    if session.cwd is None:
        rec_path = os.path.join(root, "usage_record.jsonl")
        if os.path.isfile(rec_path):
            try:
                with open(rec_path, "r", encoding="utf-8") as handle:
                    for line in handle:
                        try:
                            d = json.loads(line)
                            if d.get("sessionId") == sid and d.get("project"):
                                session.note_cwd(d["project"])
                                break
                        except ValueError:
                            continue
            except OSError:
                pass

    # 3. Read billed token requests from usage/token-usage-*.jsonl
    usage_files = _find_usage_files(root)
    # If path itself is a token-usage file, make sure it is included
    if base_name.startswith("token-usage-") and path not in usage_files:
        usage_files.append(path)

    for u_path in usage_files:
        records = _read_usage_records(u_path)
        for rec in records:
            if not isinstance(rec, dict):
                continue
            rec_sid = rec.get("sessionId")
            # If path was a token-usage file and we didn't have a specific sid, adopt first sid
            if base_name.startswith("token-usage-") and sid.startswith("token-usage-") and rec_sid:
                sid = rec_sid
                session.id = sid

            if rec_sid != sid:
                continue

            ts = parse_iso(rec.get("timestamp"))
            session.note_time(ts)

            model = rec.get("model") or "qwen"
            inp = int(rec.get("inputTokens") or 0)
            out = int(rec.get("outputTokens") or 0)
            cached = int(rec.get("cachedTokens") or 0)
            thoughts = int(rec.get("thoughtsTokens") or 0)

            # Follow base.py semantics: input is non-cached input tokens,
            # output includes thinking tokens, cache_read is cached tokens.
            non_cached_in = max(0, inp - cached)
            req_id = rec.get("id") or "req_%d" % len(session.messages)
            key = f"qwen:{sid}:{req_id}"

            session.messages.append(
                Message(
                    ts=ts or session.origin_ts or 0.0,
                    model=str(model),
                    input=non_cached_in,
                    output=out,
                    cache_read=cached,
                    cache_write=0,
                    thinking=thoughts,
                    cwd=session.cwd,
                    branch=session.branch,
                    key=key,
                )
            )

    return session
