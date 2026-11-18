"""Output speed (tokens/s) and TTFT histogram helpers, ported from Tokei."""

from __future__ import annotations

import math
from typing import Dict, Mapping, Optional, Tuple, Union

MIN_OUTPUT = 20
MIN_SECONDS = 0.2
MAX_SECONDS = 1800.0
MAX_TPS = 3000.0
MAX_TTFT = 120.0
TTFT_BASE = 0.05
TTFT_RATIO = 1.05


def ttft_bucket(seconds: float) -> int:
    """Bucket 0 = [0, 0.05); bucket k >= 1 = [0.05 * 1.05^(k-1), 0.05 * 1.05^k)."""
    if seconds < TTFT_BASE:
        return 0
    return int(math.floor(math.log(seconds / TTFT_BASE) / math.log(TTFT_RATIO))) + 1


def ttft_bounds(bucket: int) -> Tuple[float, float]:
    """Lower and upper seconds for a TTFT histogram bucket."""
    if bucket <= 0:
        return 0.0, TTFT_BASE
    return (
        TTFT_BASE * (TTFT_RATIO ** (bucket - 1)),
        TTFT_BASE * (TTFT_RATIO ** bucket),
    )


def accept_sample(out_tokens, gen_seconds) -> Optional[Tuple[int, float]]:
    """Return ``(out, gen)`` when a request sample passes quality filters, else ``None``."""
    try:
        out = int(out_tokens or 0)
        gen = float(gen_seconds or 0.0)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(gen):
        return None
    if out < MIN_OUTPUT or not (MIN_SECONDS < gen <= MAX_SECONDS) or out / gen > MAX_TPS:
        return None
    return out, gen


def add_sample(perf: dict, key, out_tokens, gen_seconds, ttft_seconds=None) -> bool:
    """Accumulate one request sample into ``perf[key]``; return True if kept."""
    accepted = accept_sample(out_tokens, gen_seconds)
    if accepted is None:
        return False
    out, gen = accepted
    stats = perf.setdefault(key, {"o": 0, "g": 0.0, "n": 0, "th": {}})
    stats["o"] += out
    stats["g"] = round(stats["g"] + gen, 3)
    stats["n"] += 1
    try:
        ttft = float(ttft_seconds) if ttft_seconds is not None else None
    except (TypeError, ValueError, OverflowError):
        ttft = None
    if ttft is not None and math.isfinite(ttft) and 0.0 <= ttft <= MAX_TTFT:
        hist = stats.setdefault("th", {})
        bucket = str(ttft_bucket(ttft))
        hist[bucket] = hist.get(bucket, 0) + 1
    return True


def merge_histograms(dst: Dict[str, int], src: Optional[Mapping[Union[str, int], int]]) -> Dict[str, int]:
    """Merge TTFT bucket counts from ``src`` into ``dst``."""
    for bucket, count in (src or {}).items():
        try:
            c = int(count or 0)
        except (TypeError, ValueError):
            continue
        if c > 0:
            key = str(bucket)
            dst[key] = dst.get(key, 0) + c
    return dst


def merge_perf(dst: dict, src: Optional[dict]) -> dict:
    """Merge ``{key: {o, g, n, th}}`` mappings from ``src`` into ``dst``."""
    for key, stats in (src or {}).items():
        if not isinstance(stats, dict):
            continue
        target = dst.setdefault(key, {"o": 0, "g": 0.0, "n": 0, "th": {}})
        target["o"] += int(stats.get("o", 0) or 0)
        target["g"] = round(target["g"] + float(stats.get("g", 0.0) or 0.0), 3)
        target["n"] += int(stats.get("n", 0) or 0)
        merge_histograms(target.setdefault("th", {}), stats.get("th"))
    return dst


def ttft_median(hist: Optional[Mapping[Union[str, int], int]]) -> Optional[float]:
    """Histogram median with linear interpolation inside the bucket (Tokei ``_perf_ttft_median``)."""
    if not hist:
        return None
    buckets = sorted(
        (int(bucket), int(count or 0))
        for bucket, count in hist.items()
        if int(count or 0) > 0
    )
    total = sum(count for _, count in buckets)
    if not total:
        return None

    def at_rank(rank: int) -> float:
        seen = 0
        for bucket, count in buckets:
            if seen + count >= rank:
                low, high = ttft_bounds(bucket)
                return low + (high - low) * ((rank - seen - 0.5) / count)
            seen += count
        return 0.0  # unreachable when 1 <= rank <= total

    # Even sample counts average both middle ranks; odd counts use the middle rank twice.
    return round((at_rank((total + 1) // 2) + at_rank((total + 2) // 2)) / 2.0, 2)


def avg_tps(o: int, g: float) -> Optional[float]:
    """Average output tokens per second from summed tokens and generation seconds."""
    if g <= 0:
        return None
    return o / g
