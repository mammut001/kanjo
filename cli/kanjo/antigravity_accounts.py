"""Attribution of Antigravity sessions and messages to Google accounts.

Antigravity logs each launch into ``~/.gemini/antigravity-cli/log/cli-YYYYMMDD_HHMMSS.log``
(and ``acp-server-YYYYMMDD_HHMMSS-<pid>.log``). Each launch span records:
- start: epoch seconds from filename timestamp (local time)
- end: max(last glog line time, file mtime), handling year rollover
- emails: set of distinct Google account emails observed in ``email=...`` lines
- conversations: conversation IDs created or active during the launch

Attribution rule (per message):
a. launches that used this conversation and whose [start-60s, end+60s] covers ts
   -> if exactly one distinct email, return it;
b. else all launches whose [start-60s, end+60s] covers ts (regardless of conversation evidence)
   -> if exactly one distinct email among them, return it;
c. else None (unknown). Never guess between two different emails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import re
import tempfile
import time
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .cache import _cache_dir
from .sources.base import Message, Session, iso_utc, local_zone

LOGS_CACHE_VERSION = 4
_FILENAME_RE = re.compile(r"(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})")
_GLOG_LINE_RE = re.compile(r"^[IWEF](\d{2})(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?")
_EMAIL_RE = re.compile(r"\bemail=([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_CONV_PATTERNS = [
    re.compile(r"Created conversation\s+([0-9a-fA-F-]{36})"),
    re.compile(r"(?:GetConversationDetail:\s+)?found conversation\s+([0-9a-fA-F-]{36})\s+\(active=true\)"),
    re.compile(r"Streaming conversation\s+([0-9a-fA-F-]{36})"),
    re.compile(r"Starting conversation update stream for\s+([0-9a-fA-F-]{36})"),
    re.compile(r"Print mode: resuming conversation\s+([0-9a-fA-F-]{36})"),
    re.compile(r"Resuming conversation\s+([0-9a-fA-F-]{36})"),
    re.compile(r"Sending user message to conversation\s+([0-9a-fA-F-]{36})"),
    re.compile(r"Forwarding user message to conversation\s+([0-9a-fA-F-]{36})"),
    re.compile(r"Stream completed for\s+([0-9a-fA-F-]{36})"),
    re.compile(r"Stream goroutine exited for\s+([0-9a-fA-F-]{36})"),
]


@dataclass
class LaunchSpan:
    path: str
    start: float
    end: float
    emails: Set[str] = field(default_factory=set)
    conversations: Set[str] = field(default_factory=set)
    auth_ts: Optional[float] = None


def parse_log_file(path: str, known_conversations: Optional[Set[str]] = None,
                   local_tz=None) -> Optional[LaunchSpan]:
    """Parse one Antigravity launch log file into a LaunchSpan."""
    fname = os.path.basename(path)
    m = _FILENAME_RE.search(fname)
    if not m:
        return None

    tz = local_tz or local_zone()
    try:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))
        hour = int(m.group(4))
        minute = int(m.group(5))
        second = int(m.group(6))
        dt_start = datetime(year, month, day, hour, minute, second, tzinfo=tz)
        start_ts = dt_start.timestamp()
    except (ValueError, OverflowError):
        return None

    emails: Set[str] = set()
    conversations: Set[str] = set()
    last_glog_ts: Optional[float] = None
    has_keyring_load: bool = False
    keyring_auth_ts: Optional[float] = None
    apply_auth_ts: Optional[float] = None

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                # 1. Glog line timestamp
                current_line_ts: Optional[float] = None
                gm = _GLOG_LINE_RE.match(line)
                if gm:
                    try:
                        l_month = int(gm.group(1))
                        l_day = int(gm.group(2))
                        l_hour = int(gm.group(3))
                        l_min = int(gm.group(4))
                        l_sec = int(gm.group(5))
                        frac = gm.group(6)
                        l_usec = int(frac.ljust(6, "0")[:6]) if frac else 0

                        # Handle year rollover (e.g. Dec -> Jan)
                        if month == 12 and l_month == 1:
                            l_year = year + 1
                        elif month == 1 and l_month == 12:
                            l_year = year - 1
                        else:
                            l_year = year

                        dt_line = datetime(l_year, l_month, l_day, l_hour, l_min, l_sec, l_usec, tzinfo=tz)
                        current_line_ts = dt_line.timestamp()
                        last_glog_ts = current_line_ts
                    except (ValueError, OverflowError):
                        pass

                # Keyring auth detection
                if "keyringAuth: loaded token" in line:
                    has_keyring_load = True
                    if current_line_ts is not None and keyring_auth_ts is None:
                        keyring_auth_ts = current_line_ts

                if "applyAuthResult: email=" in line:
                    if current_line_ts is not None and apply_auth_ts is None:
                        apply_auth_ts = current_line_ts

                # 2. Email detection
                for em in _EMAIL_RE.findall(line):
                    clean_em = em.strip().lower()
                    if clean_em:
                        emails.add(clean_em)

                # 3. Conversation detection (created, active, streaming)
                for pat in _CONV_PATTERNS:
                    for cid in pat.findall(line):
                        clean_cid = cid.strip().lower()
                        if known_conversations is not None and clean_cid not in known_conversations:
                            continue
                        conversations.add(clean_cid)
    except OSError:
        return None

    try:
        file_mtime = os.stat(path).st_mtime
    except OSError:
        file_mtime = start_ts

    candidates = [start_ts, file_mtime]
    if last_glog_ts is not None:
        candidates.append(last_glog_ts)
    end_ts = max(candidates)

    auth_ts: Optional[float] = None
    if has_keyring_load:
        if keyring_auth_ts is not None:
            auth_ts = keyring_auth_ts
        elif apply_auth_ts is not None:
            auth_ts = apply_auth_ts
        else:
            auth_ts = start_ts

    return LaunchSpan(
        path=path,
        start=start_ts,
        end=end_ts,
        emails=emails,
        conversations=conversations,
        auth_ts=auth_ts,
    )


def log_dirs(roots: Optional[List[str]] = None) -> List[str]:
    """Return sibling log directories for the given (or discovered) Antigravity conversation roots."""
    from .sources import antigravity
    conv_roots = roots if roots is not None else antigravity.roots()
    found: List[str] = []
    for r in conv_roots:
        r_clean = r.rstrip("/\\")
        candidates = []
        if os.path.basename(r_clean) == "conversations":
            candidates.append(os.path.join(os.path.dirname(r_clean), "log"))
        else:
            candidates.append(os.path.join(r_clean, "log"))
            candidates.append(os.path.join(os.path.dirname(r_clean), "log"))
        for cand in candidates:
            if os.path.isdir(cand) and cand not in found:
                found.append(cand)
    return found


class AntigravityAccountIndex:
    """Index of Antigravity launch spans and account attribution engine."""

    def __init__(self, dirs: Optional[List[str]] = None, cache_dir: Optional[str] = None,
                 known_conversations: Optional[Set[str]] = None):
        self.dirs = dirs if dirs is not None else log_dirs()
        self.cache_dir = cache_dir or _cache_dir()
        self.known_conversations = known_conversations
        self.spans: List[LaunchSpan] = []
        self._spans_by_conv: Dict[str, List[LaunchSpan]] = {}
        self._build_index()

    def _cache_path(self) -> str:
        return os.path.join(self.cache_dir, f"antigravity-logs-cache-v{LOGS_CACHE_VERSION}.json")

    def _load_cache(self) -> Dict[str, dict]:
        path = self._cache_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data.get("version") == LOGS_CACHE_VERSION:
                return data.get("files") or {}
        except (OSError, ValueError):
            pass
        return {}

    def _save_cache(self, files: Dict[str, dict]) -> None:
        path = self._cache_path()
        tmp = None
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=".antigravity-logs-cache-", dir=self.cache_dir)
            payload = {"version": LOGS_CACHE_VERSION, "files": files}
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            del data
            os.replace(tmp, path)
        except OSError:
            pass
        finally:
            if tmp is not None and os.path.exists(tmp):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    def _build_index(self) -> None:
        cached_files = self._load_cache()
        new_cached_files: Dict[str, dict] = {}
        dirty = False

        for d in self.dirs:
            if not os.path.isdir(d):
                continue
            try:
                entries = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                continue

            for entry in entries:
                if not entry.name.endswith(".log"):
                    continue
                if not _FILENAME_RE.search(entry.name):
                    continue

                path = entry.path
                try:
                    st = entry.stat()
                except OSError:
                    continue

                sig = [st.st_size, st.st_mtime_ns]
                cached_entry = cached_files.get(path)

                span = None
                if cached_entry and cached_entry.get("sig") == sig:
                    try:
                        span = LaunchSpan(
                            path=path,
                            start=float(cached_entry["start"]),
                            end=float(cached_entry["end"]),
                            emails=set(cached_entry.get("emails") or []),
                            conversations=set(cached_entry.get("conversations") or []),
                            auth_ts=float(cached_entry["auth_ts"]) if cached_entry.get("auth_ts") is not None else None,
                        )
                        new_cached_files[path] = cached_entry
                    except (KeyError, ValueError, TypeError):
                        span = None

                if span is None:
                    span = parse_log_file(path, known_conversations=self.known_conversations)
                    if span is not None:
                        new_cached_files[path] = {
                            "sig": sig,
                            "start": span.start,
                            "end": span.end,
                            "auth_ts": span.auth_ts,
                            "emails": sorted(span.emails),
                            "conversations": sorted(span.conversations),
                        }
                        dirty = True

                if span is not None:
                    self.spans.append(span)
                    if span.conversations:
                        for cid in span.conversations:
                            self._spans_by_conv.setdefault(cid, []).append(span)

        self.spans.sort(key=lambda s: s.start)
        if dirty:
            self._save_cache(new_cached_files)

    def attribute(self, conversation_id: str, ts: float) -> Optional[str]:
        """Attribute a message timestamp to an account email.

        a. launches that used this conversation and whose [start-60s, end+60s] covers ts
           -> if exactly one distinct email, return it;
        b. else all launches whose [start-60s, end+60s] covers ts (regardless of conversation evidence)
           -> if exactly one distinct email among them, return it;
        c. else None (unknown). Never guess between two different emails.
        """
        cid = conversation_id.lower()

        # a. launches that used this conversation and whose [start-60s, end+60s] covers ts
        matches_a = [
            span for span in self._spans_by_conv.get(cid, [])
            if (span.start - 60.0) <= ts <= (span.end + 60.0)
        ]
        if matches_a:
            emails_a = {e for span in matches_a for e in span.emails}
            if len(emails_a) == 1:
                return next(iter(emails_a))
            return None

        # b. else all launch spans covering ts (regardless of conversation evidence)
        matches_b = []
        for span in self.spans:
            if (span.start - 60.0) > ts:
                break
            if ts <= (span.end + 60.0):
                matches_b.append(span)

        if matches_b:
            emails_b = {e for span in matches_b for e in span.emails}
            if len(emails_b) == 1:
                return next(iter(emails_b))
            return None

        # c. else None (unknown)
        return None

    def get_current_account(self) -> Optional[str]:
        """Return the signed-in Google email from the most recent launch span."""
        for span in reversed(self.spans):
            if len(span.emails) == 1:
                return next(iter(span.emails))
        return None


def list_accounts(sessions: Iterable[Session]) -> List[dict]:
    """Aggregate Antigravity sessions/messages by account.

    Returns rows with: account, messages, tokens, total_tokens, first_seen, last_seen,
    with an "unknown" row always placed at the end.
    """
    stats: Dict[str, dict] = {}
    for s in sessions:
        if s.agent != "antigravity":
            continue
        for m in s.messages:
            acc = m.account.lower() if m.account else "unknown"
            if acc not in stats:
                stats[acc] = {
                    "account": acc,
                    "messages": 0,
                    "tokens": 0,
                    "first_seen": None,
                    "last_seen": None,
                }
            entry = stats[acc]
            entry["messages"] += 1
            tok = m.input + m.output + m.cache_read + m.cache_write
            entry["tokens"] += tok
            if entry["first_seen"] is None or m.ts < entry["first_seen"]:
                entry["first_seen"] = m.ts
            if entry["last_seen"] is None or m.ts > entry["last_seen"]:
                entry["last_seen"] = m.ts

    # Ensure "unknown" is present even if 0 messages
    if "unknown" not in stats:
        stats["unknown"] = {
            "account": "unknown",
            "messages": 0,
            "tokens": 0,
            "first_seen": None,
            "last_seen": None,
        }

    known_rows = [stats[k] for k in sorted(stats.keys()) if k != "unknown"]
    known_rows.sort(key=lambda r: (-r["messages"], r["account"]))
    all_rows = known_rows + [stats["unknown"]]

    out = []
    for r in all_rows:
        out.append({
            "account": r["account"],
            "messages": r["messages"],
            "tokens": r["tokens"],
            "total_tokens": r["tokens"],
            "first_seen": iso_utc(r["first_seen"]) if r["first_seen"] is not None else None,
            "last_seen": iso_utc(r["last_seen"]) if r["last_seen"] is not None else None,
        })
    return out


_INDEX: Optional[AntigravityAccountIndex] = None


def get_account_index(log_dirs: Optional[List[str]] = None, cache_dir: Optional[str] = None,
                      force_refresh: bool = False,
                      known_conversations: Optional[Set[str]] = None) -> AntigravityAccountIndex:
    """Retrieve or create the process-level Antigravity account index."""
    global _INDEX
    if _INDEX is None or force_refresh or log_dirs is not None:
        _INDEX = AntigravityAccountIndex(dirs=log_dirs, cache_dir=cache_dir,
                                         known_conversations=known_conversations)
    return _INDEX


def reset_account_index() -> None:
    """Reset the process-level account index (useful for tests)."""
    global _INDEX
    _INDEX = None


def attribute(conversation_id: str, ts: float) -> Optional[str]:
    """Module-level attribution helper using the process-level index."""
    return get_account_index().attribute(conversation_id, ts)
