"""Quota windows for CONTRACT.md ``quota_windows`` (best effort).

Sources, per agent, highest priority first:

1. ``[quota_windows.<agent>]`` in the user config (``source: "manual"``).
2. Tokei's caches in ``~/.tokei`` (``$KANJO_TOKEI_DIR``), ``source: "tokei"``:
   - Claude: ``claude_quota_swift_cache.json`` -> ``snapshot.q7Reset`` (weekly) and
     ``snapshot.q5Reset`` (5-hour), epoch seconds; freshness from ``snapshot.updated``.
   - Codex: ``codex_quota_cache.json`` -> ``limits.secondary`` (weekly, ``window_minutes``)
     and ``limits.primary`` (5-hour) ``resets_at``; freshness from ``fetched_at``.

A Tokei cache older than ``MAX_AGE_DAYS`` is ignored. Anything missing or malformed
just leaves that agent out; this module never raises.

Reset points that are already past are moved forward: the weekly reset by whole
windows (the cadence is fixed), the 5-hour reset becomes null (the next 5-hour
window only starts with the next use).
"""

from __future__ import annotations

import json
import math
import os
import time
from typing import Dict, Optional

from .sources.base import iso_utc

MAX_AGE_DAYS = 14
DEFAULT_WEEKLY_HOURS = 168
CLAUDE_FILE = "claude_quota_swift_cache.json"
CODEX_FILE = "codex_quota_cache.json"


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


def window(weekly: float, hours: int, five: Optional[float], source: str, now: float) -> dict:
    period = hours * 3600
    if weekly <= now:
        weekly += period * (math.floor((now - weekly) / period) + 1)
    if five is not None and five <= now:
        five = None
    return {
        "weekly_resets_at": iso_utc(weekly),
        "weekly_window_hours": int(hours),
        "five_hour_resets_at": iso_utc(five),
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
    return window(weekly, DEFAULT_WEEKLY_HOURS, _num(snap.get("q5Reset")), "tokei", now)


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
    return window(weekly, hours or DEFAULT_WEEKLY_HOURS, _num(primary.get("resets_at")), "tokei", now)


TOKEI_READERS = {"claude": _claude, "codex": _codex}


def quota_windows(manual: Optional[Dict[str, dict]] = None, directory: Optional[str] = None,
                  now: Optional[float] = None) -> Dict[str, dict]:
    """agent -> contract ``quota_windows`` entry. ``manual`` is ``Config.quota_windows``."""
    now = time.time() if now is None else now
    directory = directory or tokei_dir()
    out: Dict[str, dict] = {}
    for agent, reader in TOKEI_READERS.items():
        try:
            entry = reader(directory, now)
        except Exception:  # unknown cache format: skip it, never break the export
            entry = None
        if entry:
            out[agent] = entry
    for agent, spec in (manual or {}).items():
        out[agent] = window(spec["weekly_resets_at"], spec["weekly_window_hours"],
                            spec.get("five_hour_resets_at"), "manual", now)
    return {agent: out[agent] for agent in sorted(out)}
