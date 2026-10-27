"""User configuration (ATTRIBUTION.md section 8).

Default location: ``~/.config/kanjo/attribution.toml``. A JSON file with the
same structure (``attribution.json``) is also accepted, since ``tomllib`` is
only in the standard library from Python 3.11. On older Pythons a small
built-in parser reads the TOML subset the documented structure uses (tables,
quoted or bare keys, strings, numbers, booleans and string arrays).

    [aliases]
    "github.com/cclank/tokei" = ["github.com/dogecoin/tokei", "/Users/dogecoin/old-tokei"]

    [overrides]
    "/Users/dogecoin/Documents/experiments/tokei-" = "github.com/cclank/tokei"

    exclude = ["/Users/dogecoin/scratch"]
    dominant_threshold = 0.8

    [quota_windows.claude]          # manual quota window, beats the Tokei cache
    weekly_resets_at = "2026-10-27T10:00:00Z"
    weekly_window_hours = 168
    five_hour_resets_at = "2026-10-24T09:30:00Z"   # optional

    [subscriptions.claude]          # manual fields override detection for this agent
    plan = "max_20x"
    monthly_price_usd = 200         # optional; known plans fill it in
    anchor_day = 25                 # optional, 1-28; sets cycle_source = "manual"

Note: in TOML a bare key after a ``[table]`` header belongs to that table, so
``exclude`` and ``dominant_threshold`` are also accepted inside any table.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Dict, List, Optional

from .quota import parse_weekly_reset
from .sources.base import AGENT_LABELS
from .subscriptions import known_monthly_price

DEFAULT_THRESHOLD = 0.8
DEFAULT_DIR = os.path.join("~", ".config", "kanjo")


class ConfigError(Exception):
    pass


@dataclass
class Config:
    aliases: Dict[str, List[str]] = field(default_factory=dict)
    overrides: Dict[str, str] = field(default_factory=dict)
    exclude: List[str] = field(default_factory=list)
    dominant_threshold: float = DEFAULT_THRESHOLD
    no_network: bool = False
    # agent -> {"weekly_reset": str, "weekly_resets_at": epoch s, "weekly_window_hours": int, "five_hour_resets_at": epoch s | None}
    quota_windows: Dict[str, dict] = field(default_factory=dict)
    quota_origins: Dict[str, dict] = field(default_factory=dict)
    # agent -> explicitly configured subscription fields
    subscriptions: Dict[str, dict] = field(default_factory=dict)
    subscription_origins: Dict[str, dict] = field(default_factory=dict)
    source: Optional[str] = None

    def match_override(self, path: Optional[str]):
        """Longest prefix among overrides and exclude -> ("override", project id),
        ("exclude", None) or None. Plain string prefix match, as documented."""
        if not path:
            return None
        best = None
        for prefix, target in self.overrides.items():
            if path.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
                best = (prefix, "override", target)
        for prefix in self.exclude:
            if path.startswith(prefix) and (best is None or len(prefix) > len(best[0])):
                best = (prefix, "exclude", None)
        return (best[1], best[2]) if best else None


# ---- minimal TOML subset -----------------------------------------------------
_BARE_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$")


def _parse_value(text: str, lineno: int):
    text = text.strip()
    if not text:
        raise ConfigError("line %d: missing value" % lineno)
    if text[0] in "\"'":
        quote = text[0]
        end = text.find(quote, 1)
        if end < 0:
            raise ConfigError("line %d: unterminated string" % lineno)
        raw = text[1:end]
        return raw.encode("utf-8").decode("unicode_escape") if quote == '"' and "\\" in raw else raw
    if text[0] == "[":
        if not text.endswith("]"):
            raise ConfigError("line %d: arrays must fit on one line" % lineno)
        inner = text[1:-1].strip()
        items = []
        while inner:
            if inner[0] in "\"'":
                quote = inner[0]
                end = inner.find(quote, 1)
                if end < 0:
                    raise ConfigError("line %d: unterminated string" % lineno)
                items.append(inner[1:end])
                inner = inner[end + 1:].lstrip()
            else:
                piece, _, inner = inner.partition(",")
                items.append(_parse_value(piece, lineno))
                inner = inner.lstrip()
                continue
            if inner.startswith(","):
                inner = inner[1:].lstrip()
        return items
    if text in ("true", "false"):
        return text == "true"
    if _BARE_DATETIME.match(text):
        return text  # TOML offset date-time; kept as a string, parsed by _parse_time
    try:
        return float(text) if any(c in text for c in ".eE") else int(text)
    except ValueError:
        raise ConfigError("line %d: cannot parse value %r" % (lineno, text))


def _strip_comment(line: str) -> str:
    out = []
    quote = None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
    return "".join(out).strip()


def parse_toml_subset(text: str) -> dict:
    data: dict = {}
    table = data
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = _strip_comment(raw)
        if not line:
            continue
        m = re.match(r"^\[\s*([A-Za-z0-9_.\-]+)\s*\]$", line)
        if m:
            table = data  # dotted headers ([quota_windows.claude]) nest, as in TOML
            for part in m.group(1).split("."):
                table = table.setdefault(part, {})
                if not isinstance(table, dict):
                    raise ConfigError("line %d: [%s] redefines a value" % (lineno, m.group(1)))
            continue
        m = re.match(r'^(?:"([^"]*)"|\'([^\']*)\'|([A-Za-z0-9_\-]+))\s*=\s*(.+)$', line)
        if not m:
            raise ConfigError("line %d: cannot parse %r" % (lineno, raw))
        key = m.group(1) if m.group(1) is not None else (m.group(2) if m.group(2) is not None else m.group(3))
        table[key] = _parse_value(m.group(4), lineno)
    return data


def _parse_text(text: str, path: str) -> dict:
    if path.endswith(".json"):
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ConfigError("%s: %s" % (path, exc))
    try:
        import tomllib  # type: ignore  # Python 3.11+
        try:
            return tomllib.loads(text)
        except Exception as exc:  # tomllib.TOMLDecodeError
            raise ConfigError("%s: %s" % (path, exc))
    except ImportError:
        return parse_toml_subset(text)


def _norm_prefix(p: str) -> str:
    return os.path.expanduser(p) if p.startswith("~") else p


def from_dict(data: dict, source: Optional[str] = None) -> Config:
    if not isinstance(data, dict):
        raise ConfigError("configuration must be a table/object")
    cfg = Config(source=source)
    # keys that TOML may have captured inside a table
    flat = dict(data)
    stack = [v for v in data.values() if isinstance(v, dict)]
    while stack:  # nested tables too: [quota_windows.claude] then a bare exclude = [...]
        value = stack.pop()
        for k in ("exclude", "dominant_threshold"):
            if k in value and k not in flat:
                flat[k] = value.pop(k)
        stack.extend(v for v in value.values() if isinstance(v, dict))
    aliases = flat.get("aliases") or {}
    if not isinstance(aliases, dict):
        raise ConfigError("[aliases] must be a table")
    for canonical, members in aliases.items():
        if isinstance(members, str):
            members = [members]
        if not isinstance(members, list):
            raise ConfigError("alias %r must be a list" % canonical)
        cfg.aliases[str(canonical)] = [str(m) for m in members]
    overrides = flat.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise ConfigError("[overrides] must be a table")
    cfg.overrides = {_norm_prefix(str(k)): str(v) for k, v in overrides.items()}
    exclude = flat.get("exclude") or []
    if isinstance(exclude, str):
        exclude = [exclude]
    cfg.exclude = [_norm_prefix(str(p)) for p in exclude]
    if "dominant_threshold" in flat:
        try:
            cfg.dominant_threshold = float(flat["dominant_threshold"])
        except (TypeError, ValueError):
            raise ConfigError("dominant_threshold must be a number")
    if not 0.0 < cfg.dominant_threshold <= 1.0:
        raise ConfigError("dominant_threshold must be in (0, 1]")
    if "no_network" in flat:
        cfg.no_network = bool(flat["no_network"])
    if flat.get("quota_windows"):
        cfg.quota_windows = _quota_windows(flat["quota_windows"])
        cfg.quota_origins = {
            agent: {key: "toml" for key in spec} for agent, spec in cfg.quota_windows.items()
        }
    if flat.get("subscriptions"):
        cfg.subscriptions = _subscriptions(flat["subscriptions"])
        cfg.subscription_origins = {
            agent: {key: "toml" for key in spec} for agent, spec in cfg.subscriptions.items()
        }
    return cfg


def _parse_time(value, where: str) -> float:
    """ISO 8601 string (or a tomllib datetime) -> epoch seconds. Naive times are UTC."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip().replace(" ", "T", 1)
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            raise ConfigError("%s: cannot parse time %r (use ISO 8601, e.g. 2026-10-27T10:00:00Z)" % (where, value))
    else:
        raise ConfigError("%s must be an ISO 8601 time string" % where)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _quota_windows(raw) -> Dict[str, dict]:
    if not isinstance(raw, dict):
        raise ConfigError("[quota_windows] must be a table")
    out = {}
    for agent, spec in raw.items():
        if agent not in AGENT_LABELS:
            raise ConfigError("unknown agent in [quota_windows]: %r" % agent)
        where = "quota_windows.%s" % agent
        if not isinstance(spec, dict):
            raise ConfigError("[%s] must be a table" % where)
        if "weekly_resets_at" not in spec and "weekly_reset" not in spec:
            raise ConfigError("[%s] needs weekly_reset or weekly_resets_at" % where)
        hours = spec.get("weekly_window_hours", 168)
        if isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours != int(hours) or hours <= 0:
            raise ConfigError("%s.weekly_window_hours must be a positive integer" % where)
        five = spec.get("five_hour_resets_at")
        entry = {
            "weekly_window_hours": int(hours),
            "five_hour_resets_at": None if five in (None, "") else _parse_time(five, where + ".five_hour_resets_at"),
        }
        if "weekly_reset" in spec:
            try:
                norm, _, _, _ = parse_weekly_reset(spec["weekly_reset"], where + ".weekly_reset")
                entry["weekly_reset"] = norm
            except ValueError as exc:
                raise ConfigError(str(exc))
        if "weekly_resets_at" in spec:
            entry["weekly_resets_at"] = _parse_time(spec["weekly_resets_at"], where + ".weekly_resets_at")
        out[str(agent)] = entry
    return out


def _subscriptions(raw) -> Dict[str, dict]:
    """Validate manual fields, keeping absent fields absent for detection to fill."""
    if not isinstance(raw, dict):
        raise ConfigError("[subscriptions] must be a table")
    out = {}
    for agent, spec in raw.items():
        if agent not in AGENT_LABELS:
            raise ConfigError("unknown agent in [subscriptions]: %r" % agent)
        where = "subscriptions.%s" % agent
        if not isinstance(spec, dict):
            raise ConfigError("[%s] must be a table" % where)
        fields = {}
        if "plan" in spec:
            plan = spec["plan"]
            if not isinstance(plan, str) or not plan.strip():
                raise ConfigError("%s.plan must be a non-empty string" % where)
            fields["plan"] = plan.strip()
        if "monthly_price_usd" in spec and spec["monthly_price_usd"] is not None:
            price = spec["monthly_price_usd"]
            if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price < 0:
                raise ConfigError("%s.monthly_price_usd must be a non-negative number" % where)
            fields["monthly_price_usd"] = float(price)
        if ("plan" in fields and "monthly_price_usd" not in fields
                and known_monthly_price(str(agent), fields["plan"]) is None):
            raise ConfigError("[%s] plan %r is unknown; set monthly_price_usd" % (where, fields["plan"]))
        anchor = spec.get("anchor_day", None)
        if anchor is not None:
            if isinstance(anchor, bool) or not isinstance(anchor, int) or not 1 <= anchor <= 28:
                raise ConfigError("%s.anchor_day must be an integer from 1 to 28" % where)
            fields["anchor_day"] = anchor
        if "extra_usage_enabled" in spec:
            extra = spec["extra_usage_enabled"]
            if not isinstance(extra, bool):
                raise ConfigError("%s.extra_usage_enabled must be true or false" % where)
            fields["extra_usage_enabled"] = extra
        out[str(agent)] = fields
    return out


def default_paths() -> List[str]:
    base = os.path.expanduser(os.environ.get("KANJO_CONFIG_DIR") or DEFAULT_DIR)
    return [os.path.join(base, "attribution.toml"), os.path.join(base, "attribution.json")]


def config_paths(path: Optional[str] = None):
    """Primary config (existing JSON fallback included), and its sibling overrides."""
    candidates = [os.path.expanduser(path)] if path else default_paths()
    primary = next((p for p in candidates if os.path.isfile(p)), candidates[0])
    return primary, os.path.join(os.path.dirname(primary), "overrides.json")


def read_overrides(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = _parse_text(handle.read(), path)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError("cannot read %s: %s" % (path, exc))
    if not isinstance(data, dict):
        raise ConfigError("%s must be an object" % path)
    return data


def load(path: Optional[str] = None, overrides: Optional[dict] = None) -> Config:
    """Explicit ``path`` must exist; otherwise the default locations are optional."""
    primary, override_path = config_paths(path)
    if os.path.isfile(primary):
        with open(primary, "r", encoding="utf-8") as handle:
            cfg = from_dict(_parse_text(handle.read(), primary), source=primary)
    elif path:
        raise ConfigError("config file not found: %s" % path)
    else:
        cfg = Config()
    data = read_overrides(override_path) if overrides is None else overrides
    raw = data.get("subscriptions", {})
    if not isinstance(raw, dict):
        raise ConfigError("overrides subscriptions must be an object")
    merged = {agent: dict(spec) for agent, spec in cfg.subscriptions.items()}
    for agent, spec in raw.items():
        if not isinstance(spec, dict):
            raise ConfigError("overrides subscriptions.%s must be an object" % agent)
        merged.setdefault(agent, {}).update(spec)
    cfg.subscriptions = _subscriptions(merged)
    for agent, spec in raw.items():
        origins = cfg.subscription_origins.setdefault(agent, {})
        for key in spec:
            if key in cfg.subscriptions[agent]:
                origins[key] = "overrides"

    raw_qw = data.get("quota_windows", {})
    if not isinstance(raw_qw, dict):
        raise ConfigError("overrides quota_windows must be an object")
    merged_qw = {agent: dict(spec) for agent, spec in cfg.quota_windows.items()}
    for agent, spec in raw_qw.items():
        if not isinstance(spec, dict):
            raise ConfigError("overrides quota_windows.%s must be an object" % agent)
        merged_qw.setdefault(agent, {}).update(spec)
    cfg.quota_windows = _quota_windows(merged_qw)
    for agent, spec in raw_qw.items():
        origins = cfg.quota_origins.setdefault(agent, {})
        for key in spec:
            if key in cfg.quota_windows[agent]:
                origins[key] = "overrides"
    return cfg


def quota_value(cfg: Config, agent: str, key: str, directory: Optional[str] = None):
    """Effective field and its origin for quota_windows."""
    spec = cfg.quota_windows.get(agent, {})
    origins = cfg.quota_origins.get(agent, {})
    if key in spec:
        return spec[key], origins.get(key, "toml")
    try:
        from .quota import tokei_dir, TOKEI_READERS
        d = directory or tokei_dir()
        reader = TOKEI_READERS.get(agent)
        if reader and reader(d, time.time()) is not None:
            return None, "tokei"
    except Exception:
        pass
    return None, "default"


def subscription_value(cfg: Config, agent: str, key: str, found: dict):
    """Effective field and its origin, including prices derived from a manual plan."""
    spec = cfg.subscriptions.get(agent, {})
    origins = cfg.subscription_origins.get(agent, {})
    if key in spec:
        return spec[key], origins.get(key, "toml")
    if key == "monthly_price_usd" and "plan" in spec:
        return known_monthly_price(agent, spec["plan"]), origins.get("plan", "toml")
    sub = found.get(agent, {})
    if key == "anchor_day":
        origin = "detected" if sub.get("cycle_source") == "subscription_date" else "default"
        return sub.get(key), origin
    if key in sub:
        return sub[key], "detected"
    return None, "default"
