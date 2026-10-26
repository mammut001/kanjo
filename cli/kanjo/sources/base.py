"""Common session model and helpers shared by the log parsers."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

AGENT_LABELS = {
    "claude": "Claude Code",
    "antigravity": "Antigravity CLI",
    "codex": "Codex CLI",
    "grok": "Grok CLI",
    "qwen": "Qwen Code",
    "commandcode": "Command Code",
    "minimax": "MiniMax",
    "opencode": "OpenCode",
    "copilot": "Copilot CLI",
}


@dataclass
class Message:
    """One billed model response."""
    ts: float                      # epoch seconds (UTC)
    model: str
    input: int = 0                 # non-cached input
    output: int = 0                # includes thinking
    cache_read: int = 0
    cache_write: int = 0
    cache_write_1h: int = 0        # part of cache_write written with 1h TTL (Claude)
    thinking: int = 0              # subset of output
    cwd: Optional[str] = None
    branch: Optional[str] = None
    key: Optional[str] = None      # global de-duplication key


@dataclass
class Session:
    id: str
    agent: str
    file: str
    started: Optional[float] = None
    ended: Optional[float] = None
    # when this session itself began (first timestamp in file order, or the
    # agent's own creation time). Forks copy older messages, so ``started``
    # alone cannot tell the original from the copy.
    origin_ts: Optional[float] = None
    cwd: Optional[str] = None
    branch: Optional[str] = None
    messages: List[Message] = field(default_factory=list)
    # one entry per tool call: the unique absolute paths that call touched
    tool_paths: List[List[str]] = field(default_factory=list)
    subagent_of: Optional[str] = None
    title: Optional[str] = None
    # extra context paths (all message cwds, workspace roots) for the cwd /
    # scratchpad fallbacks; cwd counts weight the fallback choice
    cwd_counts: Dict[str, int] = field(default_factory=dict)
    # path -> git remote URL recorded by the agent itself
    remote_hints: Dict[str, str] = field(default_factory=dict)

    def note_time(self, ts: Optional[float]) -> None:
        if ts is None:
            return
        if self.started is None or ts < self.started:
            self.started = ts
        if self.ended is None or ts > self.ended:
            self.ended = ts

    def note_cwd(self, cwd: Optional[str], weight: int = 1) -> None:
        if cwd:
            self.cwd_counts[cwd] = self.cwd_counts.get(cwd, 0) + weight
            if self.cwd is None:
                self.cwd = cwd


class ParseError(Exception):
    """The file is not in a format this parser understands."""


def parse_iso(ts) -> Optional[float]:
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Python 3.9 fromisoformat accepts at most 6 fractional digits
    m = re.match(r"^(.*?\.\d{1,6})\d*(.*)$", s)
    if m:
        s = m.group(1) + m.group(2)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def iso_utc(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_day(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def local_timezone_name() -> str:
    """IANA name of the zone ``local_day`` uses: $TZ, else the /etc/localtime
    symlink target (macOS and most Linux), else /etc/timezone, else UTC."""
    tz = os.environ.get("TZ", "").lstrip(":")
    if tz and "/" in tz and not tz.startswith("/"):
        return tz
    candidates = [tz] if tz.startswith("/") else []
    candidates.append("/etc/localtime")
    for link in candidates:
        try:
            target = os.path.realpath(link)
        except OSError:
            continue
        marker = "zoneinfo/"
        if marker in target:
            return target.split(marker, 1)[1]
    try:
        with open("/etc/timezone", "r", encoding="utf-8") as handle:
            name = handle.read().strip()
            if name:
                return name
    except OSError:
        pass
    offset = datetime.now().astimezone().utcoffset()
    if not offset:
        return "UTC"
    # no IANA name available: Etc/GMT zones have inverted signs
    hours = int(offset.total_seconds() // 3600)
    return "Etc/GMT%+d" % (-hours) if offset.total_seconds() % 3600 == 0 else "UTC"


def short_title(text) -> Optional[str]:
    if not isinstance(text, str):
        return None
    t = " ".join(text.split())
    if not t:
        return None
    return t[:80]


# ---- path extraction -------------------------------------------------------
# An absolute (or ~/) path in free text. It must start the text or follow a
# separator, so "https://host/x" and "a/b" do not match. Parsing stops at
# whitespace, quotes, semicolons and backticks (ATTRIBUTION.md section 9), and
# at shell operators.
_UNQUOTED_PATH = re.compile(r"""(?<![^\s"'`=(<>|&;,])((?:~|/)[^\s"'`;|&<>(){}$,]*)""")
_QUOTED_PATH = re.compile(r"""(["'])((?:~|/)[^"'\n`;]*?)\1""")
_TRAILING = ".,:;)]}\\"


def _finish(path: str, home: str) -> Optional[str]:
    p = path.rstrip(_TRAILING)
    if p.startswith("~"):
        if not (p == "~" or p.startswith("~/")):
            return None
        p = home + p[1:]
    if not p.startswith("/") or len(p) < 2 or p.startswith("//"):
        return None
    if not re.match(r"^/[A-Za-z0-9._~\-]", p):
        return None
    return os.path.normpath(p)


def extract_paths(text: str, home: Optional[str] = None) -> List[str]:
    """Absolute paths mentioned in a shell command (or similar free text).
    Quoted paths may contain spaces; an unquoted path inside a quoted span is
    not counted again."""
    if not text or not isinstance(text, str) or ("/" not in text and "~" not in text):
        return []
    home = home or os.path.expanduser("~")
    found: List[str] = []
    spans = []
    for m in _QUOTED_PATH.finditer(text):
        p = _finish(m.group(2), home)
        spans.append((m.start(), m.end()))
        if p:
            found.append(p)
    for m in _UNQUOTED_PATH.finditer(text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        p = _finish(m.group(1), home)
        if p:
            found.append(p)
    return found


def absolutize(path, cwd: Optional[str], home: Optional[str] = None) -> Optional[str]:
    """A path value from a tool argument: absolute, ~/, file:// or relative to cwd."""
    if not isinstance(path, str):
        return None
    p = path.strip()
    if not p or "\n" in p or len(p) > 4096:
        return None
    if p.startswith("file://"):
        from urllib.parse import unquote
        p = unquote(p[len("file://"):])
    if p.startswith("~/") or p == "~":
        p = (home or os.path.expanduser("~")) + p[1:]
    if not p.startswith("/"):
        if not cwd or re.match(r"^[a-z][a-z0-9+.\-]*:", p, re.I):
            return None
        p = os.path.join(cwd, p)
    return os.path.normpath(p)


def unique(items: Iterable[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def env_dirs(var: str, defaults: List[str]) -> List[str]:
    value = os.environ.get(var)
    if value:
        return [os.path.expanduser(p) for p in value.split(os.pathsep) if p]
    return [os.path.expanduser(p) for p in defaults]


def paths_from_args(args, cwd: Optional[str], path_keys, cmd_keys, home: Optional[str] = None) -> List[str]:
    """Paths in a tool call's argument dict. ``path_keys`` hold a path (or a
    list of paths); ``cmd_keys`` hold shell text that is scanned for absolute
    paths. Key matching is case-insensitive."""
    out: List[str] = []
    if not isinstance(args, dict):
        return out
    for key, value in args.items():
        k = str(key).lower()
        if k in path_keys:
            values = value if isinstance(value, list) else [value]
            for v in values:
                p = absolutize(v, cwd, home)
                if p:
                    out.append(p)
        elif k in cmd_keys:
            if isinstance(value, list):
                value = " ".join(str(v) for v in value)
            out.extend(extract_paths(value, home))
    return out


def git_branch(cwd: Optional[str]) -> Optional[str]:
    """Recover branch name from .git/HEAD in cwd (or linked worktree) without invoking git."""
    if not cwd or not os.path.isdir(cwd):
        return None
    dotgit = os.path.join(cwd, ".git")
    head_file = None
    if os.path.isdir(dotgit):
        head_file = os.path.join(dotgit, "HEAD")
    elif os.path.isfile(dotgit):
        try:
            with open(dotgit, "r", encoding="utf-8") as f:
                line = f.read().strip()
                if line.startswith("gitdir:"):
                    gdir = line.split(":", 1)[1].strip()
                    if not os.path.isabs(gdir):
                        gdir = os.path.normpath(os.path.join(cwd, gdir))
                    head_file = os.path.join(gdir, "HEAD")
        except OSError:
            pass
    if head_file and os.path.isfile(head_file):
        try:
            with open(head_file, "r", encoding="utf-8") as hf:
                c = hf.read().strip()
                if c.startswith("ref: refs/heads/"):
                    return c[len("ref: refs/heads/"):].strip()
        except OSError:
            pass
    return None


@contextlib.contextmanager
def open_sqlite_ro(path: str):
    """Open SQLite db in read-only mode, safely copying db + -wal + -shm to temp
    so uncheckpointed WAL rows are accessible without write-locking or touching source files.
    """
    if not os.path.isfile(path):
        raise ParseError("database file not found: %s" % path)
    tmp_dir = tempfile.mkdtemp(prefix="kanjo-db-")
    try:
        tmp_db = os.path.join(tmp_dir, os.path.basename(path))
        shutil.copy2(path, tmp_db)
        wal_path = path + "-wal"
        if os.path.isfile(wal_path):
            try:
                shutil.copy2(wal_path, tmp_db + "-wal")
            except OSError:
                pass
        shm_path = path + "-shm"
        if os.path.isfile(shm_path):
            try:
                shutil.copy2(shm_path, tmp_db + "-shm")
            except OSError:
                pass
        conn = sqlite3.connect(tmp_db)
        try:
            yield conn
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as exc:
        raise ParseError("cannot open database %s: %s" % (path, exc))
    finally:
        if os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)

