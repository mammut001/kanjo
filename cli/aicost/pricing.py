"""Model price lookup.

Price data is reused from Tokei (https://github.com/cclank/tokei, MIT License):

* ``pricing.json``            -- copy of Tokei's OpenRouter-derived catalog
                                 (Tokei commit 67bb6db, 2026-09-23).
* ``pricing_overrides.json``  -- copy of Tokei's local corrections and aliases.
* ``BUILTIN_PRICES`` below    -- Tokei's ``_DEFAULT_PRICES`` (official API prices
                                 for models the catalog had not listed yet).

Layering is the same as Tokei: builtin < pricing.json < overrides.
Prices are USD per 1M tokens.

Resolution order for a model name (ATTRIBUTION.md section 7):

1. alias from pricing_overrides.json, or the normalized id is in the catalog
   -> exact price, ``estimated = False``;
2. the closest known model: strip trailing variant suffixes
   (``gemini-3.8-flash-n`` -> ``gemini-3.8-flash``,
   ``claude-opus-5-5-high`` -> ``claude-opus-5.5``) or take the previous
   version on the same version line                       -> ``estimated = True``;
3. family keyword fallback (most expensive tier of the family, see
   ``FAMILY_FALLBACK``)                                   -> ``estimated = True``.
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.dirname(_HERE)

# Tokei's _DEFAULT_PRICES (usage.30s.py), official API prices.
BUILTIN_PRICES = {
    "anthropic/claude-fable-5.1": {"in": 10.0, "out": 50.0, "cache_read": 0.25, "cache_write": 12.5, "write1h": 20.0},
    "anthropic/claude-sonnet-5": {"in": 2.0, "out": 10.0, "cache_read": 0.2, "cache_write": 2.5},
    "anthropic/claude-sonnet-5.5": {"in": 2.0, "out": 10.0, "cache_read": 0.2, "cache_write": 2.5},
    "anthropic/claude-opus-5.5": {"in": 4.0, "out": 20.0, "cache_read": 0.2, "cache_write": 5.0},
    "anthropic/claude-haiku-5.5": {"in": 0.1, "out": 0.5, "cache_read": 0.01, "cache_write": 0.125},
    "anthropic/claude-opus-4.8": {"in": 5.0, "out": 25.0, "cache_read": 0.5, "cache_write": 6.25},
    "anthropic/claude-sonnet-4.6": {"in": 3.0, "out": 15.0, "cache_read": 0.3, "cache_write": 3.75},
    "anthropic/claude-haiku-4.5": {"in": 1.0, "out": 5.0, "cache_read": 0.1, "cache_write": 1.25},
    "openai/gpt-5.6-sol": {"in": 4.0, "out": 20.0, "cache_read": 0.4, "cache_write": 5.0},
    "openai/gpt-5.6-terra": {"in": 2.0, "out": 12.0, "cache_read": 0.2, "cache_write": 2.5},
    "openai/gpt-5.6-luna": {"in": 0.2, "out": 1.2, "cache_read": 0.02, "cache_write": 0.25},
    "openai/gpt-5.5": {"in": 5.0, "out": 30.0, "cache_read": 0.5, "cache_write": 0.0},
    "openai/gpt-6-astra": {"in": 10.0, "out": 50.0, "cache_read": 1.0, "cache_write": 12.5},
    "openai/gpt-6-sol": {"in": 2.0, "out": 10.0, "cache_read": 0.2, "cache_write": 2.5},
    "openai/gpt-6.1-sol": {"in": 2.0, "out": 10.0, "cache_read": 0.1, "cache_write": 2.5},
    "openai/gpt-6-luna": {"in": 0.1, "out": 0.5, "cache_read": 0.01, "cache_write": 0.125},
    "qwen/qwen3.8-max": {"in": 2.0, "out": 6.0, "cache_read": 0.25, "cache_write": 2.5},
    "qwen/qwen3.7-max": {"in": 1.25, "out": 3.75, "cache_read": 0.25, "cache_write": 1.5625},
    "deepseek/deepseek-v4-pro": {"in": 0.66, "out": 1.98, "cache_read": 0.022, "cache_write": 0.0},
    "google/gemini-3.5-flash": {"in": 1.5, "out": 9.0, "cache_read": 0.15, "cache_write": 0.0833},
    "google/gemini-3.1-pro-preview": {"in": 2.0, "out": 12.0, "cache_read": 0.2, "cache_write": 0.375},
    "x-ai/grok-4.6": {"in": 2.0, "out": 6.0, "cache_read": 0.5, "cache_write": 0.0},
    "x-ai/grok-4.5": {"in": 2.0, "out": 6.0, "cache_read": 0.3, "cache_write": 0.0},
    "tencent/hy3": {"in": 0.14, "out": 0.58, "cache_read": 0.035, "cache_write": 0.0},
}

# Tokei's _CLAUDE_LONG_PROMPT_TIERS: (prompt token limit, multiplier for the whole request).
LONG_PROMPT_TIERS = {
    "anthropic/claude-haiku-5.5": (100_000, 5.0),
}

# Family keyword -> representative id. Tier keywords use Tokei's _FAMILY table;
# vendor-only names (no tier in the name) fall back to the vendor's most
# expensive tier. First match wins.
FAMILY_FALLBACK = [
    ("fable", "anthropic/claude-fable-5.1"),
    ("opus", "anthropic/claude-opus-4.8"),
    ("sonnet", "anthropic/claude-sonnet-5"),
    ("haiku", "anthropic/claude-haiku-4.5"),
    ("gemini", None),  # handled specially: pro vs flash
    ("gpt-5", "openai/gpt-5.6-sol"),
    ("qwen", "qwen/qwen3.8-max"),
    ("deepseek", "deepseek/deepseek-v4-pro"),
    ("grok", "x-ai/grok-4.6"),
    ("glm", "z-ai/glm-5.2"),
    ("mimo", "xiaomi/mimo-v2.5-pro"),
    ("hy3", "tencent/hy3"),
    # vendor-only: most expensive tier of the vendor
    ("claude", "anthropic/claude-fable-5.1"),
    ("gpt", "openai/gpt-6-astra"),
    ("codex", "openai/gpt-6-astra"),
    ("openai", "openai/gpt-6-astra"),
]
GEMINI_PRO = "google/gemini-3.1-pro-preview"
GEMINI_FLASH = "google/gemini-3.5-flash"  # most expensive flash tier

# Last resort when nothing in the name identifies a family: the agent's vendor.
AGENT_DEFAULT = {
    "claude": "anthropic/claude-fable-5.1",
    "codex": "openai/gpt-6-astra",
    "antigravity": GEMINI_PRO,
}
GLOBAL_DEFAULT = "anthropic/claude-fable-5.1"

ZERO = {"in": 0.0, "out": 0.0, "cache_read": 0.0, "cache_write": 0.0, "write1h": 0.0}

_MODEL_LINE_RE = re.compile(r"^(.*?)(\d+)(?:\.(\d+))?((?:-[a-z][a-z0-9.]*)*)$")
_UNSTABLE_SUFFIX_RE = re.compile(r"(?:-(?:preview|latest|exp|\d{8}|\d{4}-\d{2}-\d{2}|\d{4}))+$")


def _load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


class PriceBook:
    def __init__(self, pricing_path=None, overrides_path=None):
        pricing_path = pricing_path or os.path.join(_DATA_DIR, "pricing.json")
        overrides_path = overrides_path or os.path.join(_DATA_DIR, "pricing_overrides.json")
        catalog = _load_json(pricing_path).get("models", {}) or {}
        overrides = _load_json(overrides_path) or {}
        self.aliases = {str(k).lower(): v for k, v in (overrides.get("aliases") or {}).items()}
        self.prices: Dict[str, dict] = {}
        for layer in (BUILTIN_PRICES, catalog, overrides.get("models") or {}):
            for model_id, price in layer.items():
                if not isinstance(price, dict):
                    continue
                merged = dict(self.prices.get(model_id, {}))
                merged.update(price)
                self.prices[model_id] = merged
        self._lines = None
        self._cache: Dict[Tuple[str, str], Tuple[Optional[str], bool]] = {}

    # ---- catalog helpers -------------------------------------------------
    def known(self, model_id):
        return bool(model_id) and model_id in self.prices

    @staticmethod
    def _model_line(name):
        base = _UNSTABLE_SUFFIX_RE.sub("", name)
        match = _MODEL_LINE_RE.match(base)
        if not match:
            return None
        version = (int(match.group(2)), int(match.group(3) or 0))
        return match.group(1), version, match.group(4), base == name

    def _line_index(self):
        if self._lines is None:
            lines = {}
            for model_id, price in self.prices.items():
                if "/" not in model_id or ":" in model_id or model_id.startswith("openrouter/"):
                    continue
                if (price.get("in") or 0) < 0 or (price.get("out") or 0) < 0:
                    continue
                provider, name = model_id.lower().rsplit("/", 1)
                line = self._model_line(name)
                if line:
                    prefix, version, tier, stable = line
                    lines.setdefault(prefix, []).append((provider, version, tier, stable, model_id))
            self._lines = lines
        return self._lines

    def _predecessor(self, normalized):
        """Same version line, highest version not above the requested one (Tokei rule)."""
        if not normalized:
            return None
        provider, _, name = normalized.lower().rpartition("/")
        line = self._model_line(name)
        if not line:
            return None
        prefix, version, tier, _stable = line
        candidates = [c for c in self._line_index().get(prefix, ())
                      if c[1] <= version and (not provider or c[0] == provider)]
        for wanted in dict.fromkeys((tier, "")):
            same = [c for c in candidates if c[2] == wanted]
            if same:
                return max(same, key=lambda c: (c[1], c[3]))[4]
        return None

    @staticmethod
    def normalize(model):
        """Local model name -> catalog-style id (port of Tokei's _normalize, trimmed)."""
        m = (model or "").strip().lower()
        if not m or m == "<synthetic>":
            return None
        m = re.sub(r"\s+", "-", m)
        m = re.sub(r"[:\-]free$", "", m)
        seg = m.rsplit("/", 1)[-1]
        if seg.startswith("muse-"):
            return "meta/" + seg
        if "/" in m:
            return m
        if m.startswith("claude"):
            m = re.sub(r"-(?:\d{8}|latest)$", "", m)
            m = re.sub(r"-(\d+)-(\d+)$", r"-\1.\2", m)
            return "anthropic/" + m
        if re.match(r"(gpt|o\d|chatgpt)", m):
            return "openai/" + m
        for prefix, vendor in (("gemini", "google"), ("grok", "x-ai"), ("qwen", "qwen"),
                               ("deepseek", "deepseek"), ("glm", "z-ai"), ("mimo", "xiaomi"),
                               ("minimax", "minimax")):
            if m.startswith(prefix):
                return vendor + "/" + m
        return m

    # ---- public API ------------------------------------------------------
    def resolve(self, model, agent=None):
        """Return (catalog id or None for zero-cost, estimated)."""
        key = (model or "", agent or "")
        if key in self._cache:
            return self._cache[key]
        result = self._resolve(model, agent)
        self._cache[key] = result
        return result

    def _resolve(self, model, agent):
        raw = (model or "").strip()
        if raw.lower() == "<synthetic>":
            return None, False
        if not raw or raw.lower() == "unknown":
            return AGENT_DEFAULT.get(agent or "", GLOBAL_DEFAULT), True
        alias = self.aliases.get(raw.lower())
        if self.known(alias):
            return alias, False
        norm = self.normalize(raw)
        if self.known(norm):
            return norm, False
        # closest known model: strip trailing variant suffixes, then version line
        low = raw.lower()
        variants = []
        parts = low.split("-")
        for cut in range(len(parts) - 1, 0, -1):
            variants.append("-".join(parts[:cut]))
        for candidate in variants:
            alias = self.aliases.get(candidate)
            if self.known(alias):
                return alias, True
            cand_norm = self.normalize(candidate)
            if self.known(cand_norm) and self._same_family(cand_norm, norm):
                return cand_norm, True
        for candidate in [norm] + [self.normalize(v) for v in variants]:
            pred = self._predecessor(candidate)
            if pred and self._same_family(pred, norm):
                return pred, True
        # family keyword fallback
        for keyword, representative in FAMILY_FALLBACK:
            if keyword in low:
                if keyword == "gemini":
                    return (GEMINI_PRO if "pro" in low else GEMINI_FLASH), True
                return representative, True
        return AGENT_DEFAULT.get(agent or "", GLOBAL_DEFAULT), True

    @staticmethod
    def _same_family(candidate, norm):
        """A stripped name must keep the vendor and enough of the name to be meaningful
        (``gemini-3`` is not a usable stand-in for ``gemini-3-flash-a``)."""
        if not candidate or not norm:
            return False
        c_vendor, _, c_name = candidate.rpartition("/")
        n_vendor, _, _ = norm.rpartition("/")
        if c_vendor != n_vendor:
            return False
        return bool(re.search(r"[a-z]", c_name.split("-")[-1])) or "." in c_name

    def price(self, model_id):
        if not model_id:
            return dict(ZERO)
        p = self.prices.get(model_id, {})
        out = {
            "in": float(p.get("in", 0.0) or 0.0),
            "out": float(p.get("out", 0.0) or 0.0),
            "cache_read": float(p.get("cache_read", 0.0) or 0.0),
            "cache_write": float(p.get("cache_write", 0.0) or 0.0),
        }
        if "write1h" in p:
            out["write1h"] = float(p["write1h"])
        elif model_id.startswith("anthropic/"):
            out["write1h"] = out["in"] * 2  # Anthropic 1h cache write = 2x input
        else:
            out["write1h"] = out["cache_write"]
        return out

    def cost(self, model, agent, input_tokens=0, output_tokens=0, cache_read=0,
             cache_write=0, cache_write_1h=0):
        """USD cost of one message. ``cache_write`` is the total cache write;
        ``cache_write_1h`` is the part of it written with the 1h TTL."""
        model_id, estimated = self.resolve(model, agent)
        if model_id is None:
            return 0.0, estimated
        p = self.price(model_id)
        w1 = min(max(cache_write_1h, 0), cache_write)
        w5 = cache_write - w1
        cost = (input_tokens * p["in"] + output_tokens * p["out"] + cache_read * p["cache_read"]
                + w5 * p["cache_write"] + w1 * p["write1h"]) / 1e6
        tier = LONG_PROMPT_TIERS.get(model_id)
        if tier and input_tokens + cache_read + cache_write > tier[0]:
            cost *= tier[1]
        return cost, estimated


_DEFAULT_BOOK = None


def default_book():
    global _DEFAULT_BOOK
    if _DEFAULT_BOOK is None:
        _DEFAULT_BOOK = PriceBook()
    return _DEFAULT_BOOK
