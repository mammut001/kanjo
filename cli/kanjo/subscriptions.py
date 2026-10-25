"""Subscription plans for CONTRACT.md ``subscriptions`` (best effort).

Sources, per agent. A manual table replaces detection for that agent
(``source: "manual"``); everyone else is detected or left out.

* Claude: ``~/.claude.json`` (``$KANJO_CLAUDE_CONFIG``). ``oauthAccount.billingType``
  must be a string containing ``subscription``. The tier is ``userRateLimitTier``
  when that value is not null, otherwise ``organizationRateLimitTier``. Substring
  match, longer keys first: ``max_20x``, ``max_5x``, ``pro``. Anything else keeps
  the raw tier and a null price. ``subscriptionCreatedAt`` sets ``anchor_day``
  (``cycle_source: "subscription_date"``); without it the anchor is the 1st
  (``calendar_month``). ``hasExtraUsageEnabled`` maps to ``extra_usage_enabled``.
* Codex: Tokei's ``codex_quota_cache.json`` in ``~/.tokei`` (``$KANJO_TOKEI_DIR``),
  with the same 14-day staleness rule as :mod:`kanjo.quota` (``fetched_at``, else
  the file mtime). Plan is ``plan`` or ``limits.plan_type``. No subscription date
  is known, so the anchor is the 1st and ``extra_usage_enabled`` is false.
* Antigravity: nothing is detectable. Only a manual table adds it.

The billing cycle is the latest ``anchor_day`` at 00:00 in the report timezone
that is still <= now, through the next month's anchor at 00:00. Each month clamps
on its own: anchor 31 is the 28th in February (the 29th in a leap year) and the
31st again in March.

List prices are public monthly prices. They can change, and ``monthly_price_usd``
in the manual table overrides them. Detection never raises.
"""

from __future__ import annotations

import calendar
import os
import re
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from .quota import CODEX_FILE, _fresh, _load, _num, tokei_dir
from .sources.base import iso_utc, local_timezone_name

# Claude keys are also substring needles and must stay longest-first.
KNOWN_PLANS = {
    "claude": {
        "max_20x": ("Claude Max 20x", 200.0),
        "max_5x": ("Claude Max 5x", 100.0),
        "pro": ("Claude Pro", 20.0),
    },
    "codex": {
        "free": ("ChatGPT Free", 0.0),
        "go": ("ChatGPT Go", 8.0),
        "plus": ("ChatGPT Plus", 20.0),
        "pro": ("ChatGPT Pro", 200.0),
        "team": ("ChatGPT Team", 30.0),
        "business": ("ChatGPT Business", 30.0),
    },
    "antigravity": {
        "google_ai_pro": ("Google AI Pro", 19.99),
        "google_ai_ultra": ("Google AI Ultra", 249.99),
    },
}

_LABEL_FAMILY = {
    "claude": "Claude",
    "codex": "ChatGPT",
    "antigravity": "Antigravity",
}


def known_monthly_price(agent: str, plan: str) -> Optional[float]:
    """List price for a known plan key, or None when this agent has no such key."""
    found = _known(agent, plan)
    return None if found is None else found[1]


def _known(agent: str, plan: str) -> Optional[Tuple[str, float]]:
    row = KNOWN_PLANS.get(agent, {}).get(plan)
    if row is None:
        return None
    return row[0], float(row[1])


def _unknown_label(agent: str, raw: str) -> str:
    return "%s (%s)" % (_LABEL_FAMILY.get(agent, agent), raw)


def _resolve(agent: str, plan: str, override) -> Tuple[str, str, Optional[float]]:
    found = _known(agent, plan)
    if found:
        label, price = found
    else:
        label, price = _unknown_label(agent, plan), None
    if override is not None:
        price = float(override)
    return plan, label, price


def _map_claude(raw: str) -> Tuple[str, str, Optional[float]]:
    for key, (label, price) in KNOWN_PLANS["claude"].items():
        if key in raw:
            return key, label, float(price)
    return raw, _unknown_label("claude", raw), None


def _claude_config_path(explicit: Optional[str]) -> str:
    if explicit:
        return os.path.expanduser(explicit)
    override = os.environ.get("KANJO_CLAUDE_CONFIG")
    return os.path.expanduser(override or os.path.join("~", ".claude.json"))


def _parse_dt(value):
    """ISO 8601 -> datetime, keeping the timestamp's own calendar (not UTC)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    # Python 3.9 fromisoformat accepts at most 6 fractional digits.
    match = re.match(r"^(.*?\.\d{1,6})\d*(.*)$", text)
    if match:
        text = match.group(1) + match.group(2)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _as_utc(now) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return datetime.fromtimestamp(float(now), timezone.utc)


def _zone(name: str):
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _shift_month(year: int, month: int, delta: int) -> Tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def _midnight(year: int, month: int, anchor: int, tz) -> datetime:
    day = min(int(anchor), calendar.monthrange(year, month)[1])
    return datetime(year, month, day, 0, 0, tzinfo=tz)


def _cycle_bounds(anchor: int, now: datetime, tz_name: str) -> Tuple[str, str]:
    """Latest anchor midnight <= now, and the next month's anchor midnight.

    Clamped per month: anchor 31 is 28 or 29 in February and 31 again in March.
    Both instants are local midnights in ``tz_name``, written as ISO 8601 UTC.
    """
    tz = _zone(tz_name)
    local = now.astimezone(tz)
    year, month = local.year, local.month
    start = _midnight(year, month, anchor, tz)
    if start > local:
        year, month = _shift_month(year, month, -1)
        start = _midnight(year, month, anchor, tz)
    end_year, end_month = _shift_month(start.year, start.month, 1)
    end = _midnight(end_year, end_month, anchor, tz)
    return iso_utc(start.timestamp()), iso_utc(end.timestamp())


def _finish(plan, label, price, anchor, cycle_source, extra, source, now, tz_name) -> dict:
    # Only a real JSON true counts. Missing, null and non-bool values stay off.
    extra_on = extra is True
    start, end = _cycle_bounds(anchor, now, tz_name)
    return {
        "plan": plan,
        "plan_label": label,
        "monthly_price_usd": None if price is None else float(price),
        "cycle_start": start,
        "cycle_end": end,
        "anchor_day": int(anchor),
        "cycle_source": cycle_source,
        "extra_usage_enabled": extra_on,
        "source": source,
    }


def _detect_claude(explicit: Optional[str], now: datetime, tz_name: str) -> Optional[dict]:
    data = _load(_claude_config_path(explicit))
    oauth = data.get("oauthAccount") if isinstance(data, dict) else None
    if not isinstance(oauth, dict):
        return None
    billing = oauth.get("billingType")
    if not isinstance(billing, str) or "subscription" not in billing:
        return None
    # A non-null userRateLimitTier wins even when the organization tier is set.
    user_tier = oauth.get("userRateLimitTier")
    chosen = user_tier if user_tier is not None else oauth.get("organizationRateLimitTier")
    if not isinstance(chosen, str) or not chosen.strip():
        return None
    plan, label, price = _map_claude(chosen.strip())
    created = _parse_dt(oauth.get("subscriptionCreatedAt"))
    if created is None:
        anchor, cycle_source = 1, "calendar_month"
    else:
        anchor, cycle_source = created.day, "subscription_date"
    return _finish(plan, label, price, anchor, cycle_source, oauth.get("hasExtraUsageEnabled"),
                   "detected", now, tz_name)


def _codex_plan(data: dict) -> Optional[str]:
    plan = data.get("plan")
    if isinstance(plan, str) and plan.strip():
        return plan.strip()
    limits = data.get("limits")
    if isinstance(limits, dict):
        plan = limits.get("plan_type")
        if isinstance(plan, str) and plan.strip():
            return plan.strip()
    return None


def _detect_codex(directory: str, now: datetime, tz_name: str) -> Optional[dict]:
    path = os.path.join(directory, CODEX_FILE)
    data = _load(path)
    if not isinstance(data, dict):
        return None
    if not _fresh(_num(data.get("fetched_at")), path, now.timestamp()):
        return None
    raw = _codex_plan(data)
    if raw is None:
        return None
    plan, label, price = _resolve("codex", raw, None)
    return _finish(plan, label, price, 1, "calendar_month", False, "detected", now, tz_name)


def _from_manual(agent: str, spec, now: datetime, tz_name: str) -> Optional[dict]:
    if not isinstance(spec, dict):
        return None
    plan = spec.get("plan")
    if not isinstance(plan, str) or not plan.strip():
        return None
    plan, label, price = _resolve(agent, plan.strip(), spec.get("monthly_price_usd"))
    anchor = spec.get("anchor_day")
    if anchor is None:
        anchor, cycle_source = 1, "calendar_month"
    else:
        cycle_source = "manual"
    return _finish(plan, label, price, anchor, cycle_source, spec.get("extra_usage_enabled", False),
                   "manual", now, tz_name)


def subscriptions(manual: Optional[Dict[str, dict]] = None, directory: Optional[str] = None,
                  claude_config: Optional[str] = None, now=None,
                  timezone_name: Optional[str] = None) -> Dict[str, dict]:
    """agent -> contract ``subscriptions`` entry. ``manual`` is ``Config.subscriptions``.

    Agents with nothing detected and no manual table are absent. Manual wins per agent.
    """
    now_dt = _as_utc(now)
    tz_name = timezone_name or local_timezone_name()
    directory = directory or tokei_dir()
    out: Dict[str, dict] = {}
    try:
        detected = _detect_claude(claude_config, now_dt, tz_name)
    except Exception:  # unexpected config shape: skip it, never break the export
        detected = None
    if detected:
        out["claude"] = detected
    try:
        detected = _detect_codex(directory, now_dt, tz_name)
    except Exception:
        detected = None
    if detected:
        out["codex"] = detected
    for agent, spec in (manual or {}).items():
        entry = _from_manual(str(agent), spec, now_dt, tz_name)
        if entry:
            out[str(agent)] = entry
    return {agent: out[agent] for agent in sorted(out)}
