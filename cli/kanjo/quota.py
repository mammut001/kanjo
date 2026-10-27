"""Quota windows for CONTRACT.md ``quota_windows`` (best effort).

Sources, per agent, highest priority first:

1. ``[quota_windows.<agent>]`` in the user config (``source: "manual"``),
   either ``weekly_reset = "tue 05:00"`` or ``weekly_resets_at = <ISO 8601>``.
2. Kanjo's direct live quota fetcher (:mod:`kanjo.quota_fetch`), ``source: "tokei"``:
   - Antigravity: local LanguageServerService on 127.0.0.1 (Gemini 5h/weekly +
     Claude/GPT group as ``extra_windows``).
   - Codex: ChatGPT usage API (5h and weekly).
   - Claude: Anthropic OAuth usage API via Keychain credentials (5h and weekly).
   - Grok: Grok billing API via ``~/.grok/auth.json`` (weekly).
   Results are cached in ``~/.local/share/kanjo/quota_cache.json`` (5 min TTL).
3. Tokei's caches in ``~/.tokei`` (``$KANJO_TOKEI_DIR``), as optional fallback:
   - Claude: ``claude_quota_swift_cache.json``
   - Codex: ``codex_quota_cache.json``
   - Grok: ``grok_quota_cache.json``

A Tokei cache older than ``MAX_AGE_DAYS`` is ignored. Anything missing or malformed
just leaves that agent out; this module never raises.

Reset points that are already past are moved forward: the weekly reset by whole
windows (the cadence is fixed), the 5-hour reset becomes null (the next 5-hour
window only starts with the next use). The used percent of a window that already ended
is null too: the cache only knows the old window. ``five_hour_window_hours`` stays set
for an ended 5-hour window (null only when the agent has none), so the UI can say so.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import math
import os
import time
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from .sources.base import iso_utc, local_timezone_name

MAX_AGE_DAYS = 14
DEFAULT_WEEKLY_HOURS = 168
CLAUDE_FILE = "claude_quota_swift_cache.json"
CODEX_FILE = "codex_quota_cache.json"
GROK_FILE = "grok_quota_cache.json"

WEEKDAYS = {
    "mon": 0, "monday": 0,
    "tue": 1, "tues": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thur": 3, "thurs": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    "sun": 6, "sunday": 6,
}
WEEKDAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_weekly_reset(value: str, where: str = "weekly_reset") -> Tuple[str, int, int, int]:
    """Parse 'tue 05:00' -> (normalized_str, weekday_idx, hour, minute)."""
    if not isinstance(value, str):
        raise ValueError(f"{where} must be a string like 'tue 05:00'")
    parts = value.strip().split()
    if len(parts) != 2:
        raise ValueError(f"{where} must be '<weekday> <HH:MM>' (e.g. 'tue 05:00')")
    w_part = parts[0].lower()
    if w_part not in WEEKDAYS:
        raise ValueError(f"{where}: unknown weekday {parts[0]!r}")
    weekday_idx = WEEKDAYS[w_part]
    t_sub = parts[1].split(":")
    if len(t_sub) != 2:
        raise ValueError(f"{where}: invalid time {parts[1]!r} (use HH:MM)")
    try:
        hour = int(t_sub[0])
        minute = int(t_sub[1])
    except ValueError:
        raise ValueError(f"{where}: invalid time {parts[1]!r} (use HH:MM)")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"{where}: time {parts[1]!r} out of range (hour 0-23, minute 0-59)")
    normalized = f"{WEEKDAY_NAMES[weekday_idx]} {hour:02d}:{minute:02d}"
    return normalized, weekday_idx, hour, minute


def next_occurrence(weekly_reset: str, now: float, tz_name: Optional[str] = None) -> float:
    """Next occurrence of weekly_reset ('tue 05:00') strictly after now, in tz_name."""
    tz = ZoneInfo(tz_name or local_timezone_name())
    now_dt = datetime.fromtimestamp(now, tz=tz)
    _, target_weekday, hour, minute = parse_weekly_reset(weekly_reset)

    candidate = datetime(now_dt.year, now_dt.month, now_dt.day, hour, minute, tzinfo=tz)
    days_ahead = (target_weekday - now_dt.weekday()) % 7
    if days_ahead == 0 and candidate.timestamp() <= now:
        days_ahead = 7

    target_date = now_dt.date() + timedelta(days=days_ahead)
    target_dt = datetime(target_date.year, target_date.month, target_date.day, hour, minute, tzinfo=tz)
    return target_dt.timestamp()


def tokei_dir() -> str:
    return os.path.expanduser(os.environ.get("KANJO_TOKEI_DIR") or os.path.join("~", ".tokei"))


def _num(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _load(path: str):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _fresh(stamp: Optional[float], path: str, now: float) -> bool:
    """``stamp`` is the cache's own fetch time; without one, the file mtime is used."""
    if stamp is None:
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return False
    return now - stamp <= MAX_AGE_DAYS * 86400


def _pct(value) -> Optional[float]:
    """Used percent 0-100 (0 allowed, clamped); None when missing or malformed."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return round(min(max(float(value), 0.0), 100.0), 1)


def window(weekly: float, hours: int, five: Optional[float], source: str, now: float,
           weekly_pct=None, five_pct=None, five_hours: Optional[float] = None) -> dict:
    period = hours * 3600
    if weekly <= now:
        weekly += period * (math.floor((now - weekly) / period) + 1)
        weekly_pct = None  # the cached usage belongs to a window that already ended
    if five is not None and five <= now:
        five = None
    if five is None:
        five_pct = None  # five_hours stays: the agent has a 5-hour window, it just ended
    return {
        "weekly_resets_at": iso_utc(weekly),
        "weekly_window_hours": int(hours),
        "weekly_used_percent": _pct(weekly_pct),
        "five_hour_resets_at": iso_utc(five),
        "five_hour_window_hours": int(round(five_hours)) if five_hours else None,
        "five_hour_used_percent": _pct(five_pct),
        "source": source,
    }


def _claude(directory: str, now: float) -> Optional[dict]:
    path = os.path.join(directory, CLAUDE_FILE)
    data = _load(path)
    snap = data.get("snapshot") if data else None
    if not isinstance(snap, dict):
        return None
    weekly = _num(snap.get("q7Reset"))
    if weekly is None or not _fresh(_num(snap.get("updated")), path, now):
        return None
    return window(weekly, DEFAULT_WEEKLY_HOURS, _num(snap.get("q5Reset")), "tokei", now,
                  snap.get("q7"), snap.get("q5"), 5 if _num(snap.get("q5Reset")) else None)


def _codex(directory: str, now: float) -> Optional[dict]:
    path = os.path.join(directory, CODEX_FILE)
    data = _load(path)
    limits = data.get("limits") if data else None
    if not isinstance(limits, dict):
        return None
    secondary = limits.get("secondary") if isinstance(limits.get("secondary"), dict) else {}
    primary = limits.get("primary") if isinstance(limits.get("primary"), dict) else {}
    weekly = _num(secondary.get("resets_at"))
    if weekly is None or not _fresh(_num(data.get("fetched_at")), path, now):
        return None
    minutes = _num(secondary.get("window_minutes"))
    hours = int(round(minutes / 60)) if minutes else DEFAULT_WEEKLY_HOURS
    return window(weekly, hours or DEFAULT_WEEKLY_HOURS, _num(primary.get("resets_at")), "tokei", now,
                  secondary.get("used_percent"), primary.get("used_percent"),
                  (_num(primary.get("window_minutes")) or 300) / 60 if _num(primary.get("resets_at")) else None)


def _grok(directory: str, now: float) -> Optional[dict]:
    path = os.path.join(directory, GROK_FILE)
    data = _load(path)
    if not isinstance(data, dict):
        return None
    quota = data.get("quota")
    if not isinstance(quota, dict):
        return None
    reset = _num(quota.get("reset"))
    if reset is None or not _fresh(_num(data.get("fetched_at")), path, now):
        return None
    win_str = quota.get("window")
    if win_str in (None, "", "week"):
        hours = DEFAULT_WEEKLY_HOURS
    elif win_str == "day":
        hours = 24
    else:
        return None
    return window(reset, hours, None, "tokei", now, quota.get("pct"))


TOKEI_READERS = {"claude": _claude, "codex": _codex, "grok": _grok}


def quota_windows(manual: Optional[Dict[str, dict]] = None, directory: Optional[str] = None,
                  now: Optional[float] = None, timezone_name: Optional[str] = None,
                  no_network: bool = False) -> Dict[str, dict]:
    """agent -> contract ``quota_windows`` entry. ``manual`` is ``Config.quota_windows``."""
    now = time.time() if now is None else now
    directory = directory or tokei_dir()
    tz_name = timezone_name or local_timezone_name()
    out: Dict[str, dict] = {}

    # 1. Tokei cache (optional fallback)
    for agent, reader in TOKEI_READERS.items():
        try:
            entry = reader(directory, now)
        except Exception:  # unknown cache format: skip it, never break the export
            entry = None
        if entry:
            out[agent] = entry

    # 2. Kanjo direct live fetch (takes precedence over Tokei fallback)
    try:
        from .quota_fetch import fetch_all_quotas
        fetched = fetch_all_quotas(now=now, no_network=no_network)
        for agent, entry in (fetched or {}).items():
            if isinstance(entry, dict) and entry.get("weekly_resets_at"):
                contract_entry = {
                    "weekly_resets_at": entry.get("weekly_resets_at"),
                    "weekly_window_hours": entry.get("weekly_window_hours", DEFAULT_WEEKLY_HOURS),
                    "weekly_used_percent": entry.get("weekly_used_percent"),
                    "five_hour_resets_at": entry.get("five_hour_resets_at"),
                    "five_hour_window_hours": entry.get("five_hour_window_hours"),
                    "five_hour_used_percent": entry.get("five_hour_used_percent"),
                    "source": "tokei",
                }
                if "extra_windows" in entry and entry["extra_windows"]:
                    contract_entry["extra_windows"] = entry["extra_windows"]
                out[agent] = contract_entry
    except Exception:
        pass

    # 3. Manual config (highest priority)
    for agent, spec in (manual or {}).items():
        if "weekly_reset" in spec:
            weekly = next_occurrence(spec["weekly_reset"], now, tz_name)
        elif "weekly_resets_at" in spec:
            weekly = spec["weekly_resets_at"]
        else:
            continue
        hours = spec.get("weekly_window_hours", DEFAULT_WEEKLY_HOURS)
        out[agent] = window(weekly, hours, spec.get("five_hour_resets_at"), "manual", now,
                             five_hours=5 if spec.get("five_hour_resets_at") is not None else None)
    return {agent: out[agent] for agent in sorted(out)}
