"""Antigravity CLI: ``~/.gemini/antigravity-cli/conversations/<id>.db`` (SQLite).

All content is protobuf without a published schema. Field numbers were
reverse engineered (the token layout follows Tokei's ``_antigravity_gen_step``,
MIT License; the rest was mapped from local databases):

``trajectory_metadata_blob.data``
    1.1  workspace URI (``file:///...``)      1.3.2  git remote URL
    1.4  git branch                            2.1    created (seconds)
``steps.metadata`` (identical to ``steps.step_payload`` field 5)
    1.1  step time (seconds)
    4    tool call: 1 id, 2 name, 3 JSON arguments
``steps.step_payload`` of user-input steps (step_type 14)
    19.2 user text
``gen_metadata.data``
    1    one generation record: 19 model, 4 {2 input (non-cached), 3 output
         (incl. thinking), 5 cache read, 9 thinking, 10 response},
         9.4.1 generation start (seconds), 20 key/value pairs
         (``root_cascade_id`` names the parent conversation of a sub-agent)
    2    packed step indexes this generation produced
"""

from __future__ import annotations

import glob
import json
import os
import sqlite3
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

from .base import Message, ParseError, Session, env_dirs, extract_paths, paths_from_args, short_title, unique

AGENT = "antigravity"
PATH_KEYS = {"absolutepath", "searchpath", "targetfile", "cwd", "directorypath", "path",
             "searchdirectory", "file", "filepath", "directory", "targetpath", "workdir"}
CMD_KEYS = {"commandline", "command", "cmd"}

_MAX_TOKENS = 100_000_000      # larger values mean the decoder is misaligned
_MIN_TS = 1_577_836_800        # 2020-01-01
_MAX_TS = 1 << 34
_USER_INPUT_STEP = 14


def roots() -> List[str]:
    return env_dirs("AICOST_ANTIGRAVITY_DIR", ["~/.gemini/antigravity-cli/conversations"])


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    found = []
    for root in dirs if dirs is not None else roots():
        if os.path.isdir(root):
            for path in sorted(glob.glob(os.path.join(root, "*.db"))):
                found.append((path, None))
    return found


# ---- protobuf wire format (ported from Tokei) ---------------------------------
def decode_varint(data: bytes, offset: int) -> Tuple[int, int]:
    val = 0
    shift = 0
    for _ in range(10):
        if offset >= len(data):
            break
        b = data[offset]
        offset += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80:
            return val, offset
        shift += 7
    raise ValueError("bad varint")


def parse_fields(data) -> List[Tuple[int, int, object]]:
    """[(field number, wire type, value)]; stops quietly at the first bad byte."""
    fields = []
    if not data:
        return fields
    i = 0
    n = len(data)
    while i < n:
        try:
            key, i = decode_varint(data, i)
            fn, wt = key >> 3, key & 7
            if wt == 0:
                val, i = decode_varint(data, i)
            elif wt == 2:
                length, i = decode_varint(data, i)
                if i + length > n:
                    break
                val = data[i:i + length]
                i += length
            elif wt in (1, 5):
                width = 8 if wt == 1 else 4
                if i + width > n:
                    break
                val = data[i:i + width]
                i += width
            else:
                break
        except (ValueError, IndexError):
            break
        fields.append((fn, wt, val))
    return fields


def _first(fields, number, wire=2):
    for fn, wt, val in fields:
        if fn == number and wt == wire:
            return val
    return None


def _text(value) -> Optional[str]:
    if not isinstance(value, (bytes, bytearray)):
        return None
    try:
        return bytes(value).decode("utf-8")
    except UnicodeDecodeError:
        return None


def _packed(data) -> List[int]:
    values = []
    i = 0
    try:
        while i < len(data):
            v, i = decode_varint(data, i)
            values.append(v)
    except ValueError:
        pass
    return values


def _valid_ts(v) -> bool:
    return isinstance(v, int) and _MIN_TS <= v <= _MAX_TS


def _uri_path(uri: Optional[str]) -> Optional[str]:
    if not uri:
        return None
    if uri.startswith("file://"):
        return unquote(uri[len("file://"):]) or None
    return uri if uri.startswith("/") else None


def gen_record(record: bytes, fallback_ts=None):
    """One generation record -> dict or None (port of Tokei's _antigravity_gen_step)."""
    model = "unknown"
    inp = out = cached = thoughts = 0
    ts = None
    for fn, wt, val in parse_fields(record):
        if fn == 19 and wt == 2:
            model = _text(val) or model
        elif fn == 4 and wt == 2:
            for tfn, twt, tval in parse_fields(val):
                if twt != 0:
                    continue
                if tfn == 2:
                    inp = tval
                elif tfn == 3:
                    out = tval
                elif tfn == 5:
                    cached = tval
                elif tfn == 9:
                    thoughts = tval
        elif fn == 9 and wt == 2:
            for tfn, twt, tval in parse_fields(val):
                if tfn == 4 and twt == 2:
                    for sfn, swt, sval in parse_fields(tval):
                        if sfn == 1 and swt == 0:
                            ts = sval
    if max(inp, out, cached, thoughts) > _MAX_TOKENS:
        return None
    if not (inp or out or cached or thoughts):
        return {"empty": True}  # failed request (quota / capacity error), nothing billed
    if not _valid_ts(ts):
        ts = fallback_ts
    if not _valid_ts(ts):
        return None
    if not model or len(model) > 120 or not model.isprintable():
        model = "unknown"
    return {"model": model, "input": inp, "output": out, "cache_read": cached,
            "thinking": min(thoughts, out) if out else thoughts, "ts": ts}


def _kv(record: bytes) -> Dict[str, str]:
    out = {}
    for fn, wt, val in parse_fields(record):
        if fn == 20 and wt == 2:
            sub = parse_fields(val)
            k, v = _text(_first(sub, 1)), _text(_first(sub, 2))
            if k and v is not None:
                out[k] = v
    return out


def _open(path: str):
    # Read-only. WAL databases without a -shm file cannot be opened with
    # mode=ro (SQLite would have to create it), so fall back to immutable.
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=1)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn
    except sqlite3.Error:
        pass
    try:
        conn = sqlite3.connect("file:%s?mode=ro&immutable=1" % path, uri=True, timeout=1)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn
    except sqlite3.Error as exc:
        raise ParseError("cannot open database: %s" % exc)


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    sid = os.path.splitext(os.path.basename(path))[0]
    session = Session(id=sid, agent=AGENT, file=path)
    conn = _open(path)
    try:
        try:
            gen_rows = conn.execute("SELECT idx, data FROM gen_metadata ORDER BY idx").fetchall()
            step_rows = conn.execute("SELECT idx, step_type, metadata FROM steps ORDER BY idx").fetchall()
        except sqlite3.Error as exc:
            raise ParseError("unexpected schema: %s" % exc)
        try:
            meta_rows = conn.execute("SELECT data FROM trajectory_metadata_blob").fetchall()
        except sqlite3.Error:
            meta_rows = []
        try:
            inputs = conn.execute(
                "SELECT step_payload FROM steps WHERE step_type = ? ORDER BY idx LIMIT 5",
                (_USER_INPUT_STEP,)).fetchall()
        except sqlite3.Error:
            inputs = []
    finally:
        conn.close()

    # trajectory metadata: workspace, remote, branch
    workspace = remote = branch = None
    for (blob,) in meta_rows:
        top = parse_fields(blob)
        ws_msg = _first(top, 1)
        if ws_msg is not None:
            ws_fields = parse_fields(ws_msg)
            workspace = workspace or _uri_path(_text(_first(ws_fields, 1)))
            git = _first(ws_fields, 3)
            if git is not None:
                remote = remote or _text(_first(parse_fields(git), 2))
            branch = branch or _text(_first(ws_fields, 4))
        created = _first(top, 2)
        if created is not None:
            secs = _first(parse_fields(created), 1, 0)
            if _valid_ts(secs):
                session.origin_ts = float(secs)
                session.note_time(float(secs))
        workspace = workspace or _uri_path(_text(_first(top, 7)))
    session.branch = branch or None
    if workspace:
        session.note_cwd(workspace, 0)
        session.cwd = workspace
        if remote:
            session.remote_hints[workspace] = remote

    # steps: timestamps and tool calls
    step_ts: Dict[int, int] = {}
    for idx, _step_type, meta in step_rows:
        fields = parse_fields(meta)
        stamp = _first(fields, 1)
        if stamp is not None:
            secs = _first(parse_fields(stamp), 1, 0)
            if _valid_ts(secs):
                step_ts[int(idx)] = secs
                session.note_time(float(secs))
        call = _first(fields, 4)
        if call is None:
            continue
        call_fields = parse_fields(call)
        args_text = _text(_first(call_fields, 3))
        if not args_text:
            continue
        try:
            args = json.loads(args_text)
        except ValueError:
            args = None
        cwd = workspace
        if isinstance(args, dict) and isinstance(args.get("Cwd"), str):
            cwd = args["Cwd"]
        found = paths_from_args(args, cwd, PATH_KEYS, CMD_KEYS) if isinstance(args, dict) else extract_paths(args_text)
        found = unique(found)
        if found:
            session.tool_paths.append(found)

    for (payload,) in inputs:
        user = _first(parse_fields(payload), 19)
        if user is not None:
            session.title = short_title(_text(_first(parse_fields(user), 2)))
            if session.title:
                break

    # generations: token usage
    root = None
    had_records = decoded_any = False
    for idx, data in gen_rows:
        if not data:
            continue
        fields = parse_fields(data)
        refs = []
        for fn, wt, val in fields:
            if fn == 2 and wt == 2:
                refs.extend(_packed(val))
        fallback = next((step_ts[r] for r in refs if r in step_ts), None)
        if fallback is None and session.started is not None:
            fallback = int(session.started)
        record_index = 0
        for fn, wt, val in fields:
            if fn != 1 or wt != 2:
                continue
            had_records = True
            rec = gen_record(val, fallback)
            if root is None:
                root = _kv(val).get("root_cascade_id")
            if rec is None:
                continue
            decoded_any = True
            if rec.get("empty"):
                continue
            session.messages.append(Message(
                ts=float(rec["ts"]), model=rec["model"], input=rec["input"], output=rec["output"],
                cache_read=rec["cache_read"], thinking=rec["thinking"], cwd=workspace, branch=branch,
                key="antigravity:%s:%s:%d" % (sid, idx, record_index)))
            session.note_time(float(rec["ts"]))
            record_index += 1
    if had_records and not decoded_any:
        raise ParseError("gen_metadata present but no generation record could be decoded")
    if root and root != sid:
        session.subagent_of = root
    return session
