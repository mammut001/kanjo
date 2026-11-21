"""Gregorian calendar operations in a report timezone (Monday = week start). Port of Time.cs."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

_DAY_CACHE: dict = {}


def _tz_key(tz) -> str:
    return getattr(tz, "key", None) or str(tz)


def start_of_day(tz, instant: datetime) -> datetime:
    instant = ensure_utc_aware(instant)
    local = instant.astimezone(tz)
    return from_local(tz, datetime(local.year, local.month, local.day))


def _is_invalid_local(tz, local: datetime) -> bool:
    naive = local.replace(tzinfo=None)
    probe = naive.replace(tzinfo=tz, fold=0)
    back = probe.astimezone(tz).replace(tzinfo=None, fold=0)
    if back == naive:
        return False
    probe1 = naive.replace(tzinfo=tz, fold=1)
    back1 = probe1.astimezone(tz).replace(tzinfo=None, fold=1)
    return back1 != naive and back != naive


def _advance_past_gap(tz, local: datetime) -> datetime:
    before = local
    for _ in range(180):
        if not _is_invalid_local(tz, before):
            break
        before = before - timedelta(minutes=1)
    after = local
    for _ in range(180):
        if not _is_invalid_local(tz, after):
            break
        after = after + timedelta(minutes=1)
    if not _is_invalid_local(tz, before) and not _is_invalid_local(tz, after):
        delta = after - (before + timedelta(minutes=1))
        if delta > timedelta(0):
            shifted = local + delta
            if not _is_invalid_local(tz, shifted):
                return shifted
    if not _is_invalid_local(tz, after):
        return after
    return local + timedelta(hours=1)


def from_local(tz, local: datetime) -> datetime:
    """Local wall-clock time → UTC-aware instant (DST gap handled like Foundation / .NET)."""
    naive = local.replace(tzinfo=None) if local.tzinfo else local
    if _is_invalid_local(tz, naive):
        naive = _advance_past_gap(tz, naive)
    for fold in (0, 1):
        try:
            aware = naive.replace(tzinfo=tz, fold=fold)
            return aware.astimezone(timezone.utc)
        except Exception:
            continue
    return naive.replace(tzinfo=timezone.utc)


def add_days(tz, instant: datetime, days: int) -> datetime:
    instant = ensure_utc_aware(instant)
    local = instant.astimezone(tz)
    d = local.date() + timedelta(days=days)
    return from_local(tz, datetime(d.year, d.month, d.day, local.hour, local.minute, local.second, local.microsecond))


def add_weeks(tz, instant: datetime, weeks: int) -> datetime:
    return add_days(tz, instant, 7 * weeks)


def at_day(tz, day: date) -> datetime:
    return from_local(tz, datetime(day.year, day.month, day.day))


def monday_offset(day: date) -> int:
    return (day.weekday()) % 7  # Monday=0 … Sunday=6


def monday_on_or_before(day: date) -> date:
    return day - timedelta(days=monday_offset(day))


def local_date(tz, instant: datetime) -> date:
    return ensure_utc_aware(instant).astimezone(tz).date()


def days_between(tz, a: datetime, b: datetime) -> int:
    return (local_date(tz, b) - local_date(tz, a)).days


def day_string(tz, instant: datetime) -> str:
    return local_date(tz, instant).isoformat()


def day_string_from_date(d: date) -> str:
    return d.isoformat()


def parse_day(s: str) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def day_range(tz, day: date) -> Tuple[datetime, datetime]:
    start = at_day(tz, day)
    end = at_day(tz, day + timedelta(days=1))
    return start, end


def cached_day_range(tz, day_str: str) -> Optional[Tuple[datetime, datetime]]:
    d = parse_day(day_str)
    if d is None:
        return None
    key = (_tz_key(tz), day_str)
    if key not in _DAY_CACHE:
        _DAY_CACHE[key] = day_range(tz, d)
    return _DAY_CACHE[key]


def ensure_utc_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def clear_day_range_cache() -> None:
    _DAY_CACHE.clear()