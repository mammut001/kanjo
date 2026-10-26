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

from .base import (
    Message, ParseError, Session, env_dirs, extract_paths,
    open_sqlite_ro, paths_from_args, short_title, unique,
)

AGENT = "antigravity"
PATH_KEYS = {"absolutepath", "searchpath", "targetfile", "cwd", "directorypath", "path",
             "searchdirectory", "file", "filepath", "directory", "targetpath", "workdir"}
CMD_KEYS = {"commandline", "command", "cmd"}

_MAX_TOKENS = 100_000_000      # larger values mean the decoder is misaligned
_MIN_TS = 1_577_836_800        # 2020-01-01
_MAX_TS = 1 << 34
_USER_INPUT_STEP = 14


def roots() -> List[str]:
    return env_dirs("KANJO_ANTIGRAVITY_DIR", ["~/.gemini/antigravity-cli/conversations"])


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    found = []
    for root in dirs if dirs is not None else roots():
        if os.path.isdir(root):
            for path in sorted(glob.glob(os.path.join(root, "*.db"))):
                found.append((path, None))
    return found


# ---- protobuf wire format (ported from Tokei) ---------------------------------
def decode_varint(data: bytes, offset: int) -> Tuple[int, int]:
    b = data[offset]
    if b < 0x80:
        return b, offset + 1
    val = b & 0x7F
    shift = 7
    offset += 1
    n = len(data)
    while offset < n:
        b = data[offset]
        offset += 1
        val |= (b & 0x7F) << shift
        if b < 0x80:
            return val, offset
        shift += 7
        if shift > 63:
            break
    raise ValueError("bad varint")


def parse_fields(data, wanted=None) -> List[Tuple[int, int, object]]:
    """[(field number, wire type, value)]; stops quietly at the first bad byte."""
    fields = []
    if not data:
        return fields
    i = 0
    n = len(data)
    while i < n:
        try:
            b = data[i]
            if b < 0x80:
                key = b
                i += 1
            else:
                key, i = decode_varint(data, i)
            fn, wt = key >> 3, key & 7
            skip = (wanted is not None and fn not in wanted)
            if wt == 0:
                if skip:
                    while i < n and data[i] >= 0x80:
                        i += 1
                    i += 1
                    continue
                b = data[i]
                if b < 0x80:
                    val = b
                    i += 1
                else:
                    val, i = decode_varint(data, i)
            elif wt == 2:
                b = data[i]
                if b < 0x80:
                    length = b
                    i += 1
                else:
                    length, i = decode_varint(data, i)
                if i + length > n:
                    break
                if skip:
                    i += length
                    continue
                val = data[i:i + length]
                i += length
            elif wt in (1, 5):
                width = 8 if wt == 1 else 4
                if i + width > n:
                    break
                if skip:
                    i += width
                    continue
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
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return None
    try:
        return bytes(value).decode("utf-8")
    except UnicodeDecodeError:
        return None


def _packed(data) -> List[int]:
    values = []
    i = 0
    try:
        n = len(data)
        while i < n:
            b = data[i]
            if b < 0x80:
                values.append(b)
                i += 1
            else:
                v, i = decode_varint(data, i)
                values.append(v)
    except (ValueError, IndexError):
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
    root_cascade_id = None
    for fn, wt, val in parse_fields(record, wanted={4, 9, 19, 20}):
        if fn == 19 and wt == 2:
            model = _text(val) or model
        elif fn == 4 and wt == 2:
            for tfn, twt, tval in parse_fields(val, wanted={2, 3, 5, 9}):
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
            for tfn, twt, tval in parse_fields(val, wanted={4}):
                if tfn == 4 and twt == 2:
                    for sfn, swt, sval in parse_fields(tval, wanted={1}):
                        if sfn == 1 and swt == 0:
                            ts = sval
        elif fn == 20 and wt == 2:
            if root_cascade_id is None:
                sub = parse_fields(val)
                k = _text(_first(sub, 1))
                if k == "root_cascade_id":
                    root_cascade_id = _text(_first(sub, 2))
    if max(inp, out, cached, thoughts) > _MAX_TOKENS:
        return None
    if not (inp or out or cached or thoughts):
        res = {"empty": True}
        if root_cascade_id:
            res["root_cascade_id"] = root_cascade_id
        return res
    if not _valid_ts(ts):
        ts = fallback_ts
    if not _valid_ts(ts):
        return None
    if not model or len(model) > 120 or not model.isprintable():
        model = "unknown"
    res = {"model": model, "input": inp, "output": out, "cache_read": cached,
           "thinking": min(thoughts, out) if out else thoughts, "ts": ts}
    if root_cascade_id:
        res["root_cascade_id"] = root_cascade_id
    return res


def _kv(record: bytes) -> Dict[str, str]:
    out = {}
    for fn, wt, val in parse_fields(record, wanted={20}):
        if fn == 20 and wt == 2:
            sub = parse_fields(val)
            k, v = _text(_first(sub, 1)), _text(_first(sub, 2))
            if k and v is not None:
                out[k] = v
    return out


def _open(path: str):
    return open_sqlite_ro(path)


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    sid = os.path.splitext(os.path.basename(path))[0]
    session = Session(id=sid, agent=AGENT, file=path)
    with open_sqlite_ro(path) as conn:
        # trajectory metadata: workspace, remote, branch
        workspace = remote = branch = None
        try:
            for (blob,) in conn.execute("SELECT data FROM trajectory_metadata_blob WHERE data IS NOT NULL"):
                top = parse_fields(blob, wanted={1, 2, 7})
                ws_msg = _first(top, 1)
                if ws_msg is not None:
                    ws_fields = parse_fields(ws_msg, wanted={1, 3, 4})
                    workspace = workspace or _uri_path(_text(_first(ws_fields, 1)))
                    git = _first(ws_fields, 3)
                    if git is not None:
                        remote = remote or _text(_first(parse_fields(git, wanted={2}), 2))
                    branch = branch or _text(_first(ws_fields, 4))
                created = _first(top, 2)
                if created is not None:
                    secs = _first(parse_fields(created, wanted={1}), 1, 0)
                    if _valid_ts(secs):
                        session.origin_ts = float(secs)
                        session.note_time(float(secs))
                workspace = workspace or _uri_path(_text(_first(top, 7)))
        except sqlite3.Error:
            pass
        session.branch = branch or None
        if workspace:
            session.note_cwd(workspace, 0)
            session.cwd = workspace
            if remote:
                session.remote_hints[workspace] = remote

        # steps: timestamps and tool calls
        step_ts: Dict[int, int] = {}
        try:
            for idx, meta in conn.execute(
                "SELECT idx, metadata FROM steps WHERE metadata IS NOT NULL ORDER BY idx"
            ):
                fields = parse_fields(meta, wanted={1, 4})
                stamp = _first(fields, 1)
                if stamp is not None:
                    secs = _first(parse_fields(stamp, wanted={1}), 1, 0)
                    if _valid_ts(secs):
                        step_ts[int(idx)] = secs
                        session.note_time(float(secs))
                call = _first(fields, 4)
                if call is None:
                    continue
                call_fields = parse_fields(call, wanted={3})
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
        except sqlite3.Error as exc:
            raise ParseError("unexpected schema: %s" % exc)

        try:
            for (payload,) in conn.execute(
                "SELECT step_payload FROM steps WHERE step_type = ? AND step_payload IS NOT NULL ORDER BY idx LIMIT 5",
                (_USER_INPUT_STEP,),
            ):
                user = _first(parse_fields(payload, wanted={19}), 19)
                if user is not None:
                    session.title = short_title(_text(_first(parse_fields(user, wanted={2}), 2)))
                    if session.title:
                        break
        except sqlite3.Error:
            pass

        # generations: token usage
        root = None
        had_records = decoded_any = False
        try:
            for idx, data in conn.execute("SELECT idx, data FROM gen_metadata WHERE data IS NOT NULL ORDER BY idx"):
                fields = parse_fields(data, wanted={1, 2})
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
                    if root is None and isinstance(rec, dict):
                        root = rec.get("root_cascade_id")
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
        except sqlite3.Error as exc:
            raise ParseError("unexpected schema: %s" % exc)

    if had_records and not decoded_any:
        raise ParseError("gen_metadata present but no generation record could be decoded")
    if root and root != sid:
        session.subagent_of = root
    return session
