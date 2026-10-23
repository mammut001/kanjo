"""User configuration (ATTRIBUTION.md section 8).

Default location: ``~/.config/aicost/attribution.toml``. A JSON file with the
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

Note: in TOML a bare key after a ``[table]`` header belongs to that table, so
``exclude`` and ``dominant_threshold`` are also accepted inside any table.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

DEFAULT_THRESHOLD = 0.8
DEFAULT_DIR = os.path.join("~", ".config", "aicost")


class ConfigError(Exception):
    pass


@dataclass
class Config:
    aliases: Dict[str, List[str]] = field(default_factory=dict)
    overrides: Dict[str, str] = field(default_factory=dict)
    exclude: List[str] = field(default_factory=list)
    dominant_threshold: float = DEFAULT_THRESHOLD
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
            table = data.setdefault(m.group(1), {})
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
    for value in data.values():
        if isinstance(value, dict):
            for k in ("exclude", "dominant_threshold"):
                if k in value and k not in flat:
                    flat[k] = value.pop(k)
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
    return cfg


def default_paths() -> List[str]:
    base = os.path.expanduser(DEFAULT_DIR)
    return [os.path.join(base, "attribution.toml"), os.path.join(base, "attribution.json")]


def load(path: Optional[str] = None) -> Config:
    """Explicit ``path`` must exist; otherwise the default locations are optional."""
    candidates = [os.path.expanduser(path)] if path else default_paths()
    for candidate in candidates:
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as handle:
                return from_dict(_parse_text(handle.read(), candidate), source=candidate)
    if path:
        raise ConfigError("config file not found: %s" % path)
    return Config()
