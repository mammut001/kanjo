"""Fallback scanner for Claude Desktop Chromium HTTP cache.

Extracts live quota utilization (5-hour and 7-day windows) from cached
Anthropic /usage API responses stored by the Claude Desktop app.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import stat
import subprocess
import time
import zlib
from datetime import datetime, timezone
from typing import Optional

DEFAULT_CLAUDE_CACHE_DIR = os.path.expanduser(
    os.path.join("~", "Library", "Application Support", "Claude", "Cache", "Cache_Data")
)
MAX_CACHE_FILES_SCANNED = 120
MAX_CACHE_FILE_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_CACHE_AGE_SECONDS = 7 * 86400       # 7 days
ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
GZIP_MAGIC = b"\x1f\x8b"


def _pct(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return round(min(max(float(value), 0.0), 100.0), 1)


def _percentage(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    val = float(value)
    if not math.isfinite(val) or val < 0:
        return None
    if 0 < val <= 1.0:
        val = val * 100.0
    return _pct(val)


def _iso_utc(ts: Optional[float]) -> Optional[str]:
    if ts is None or not math.isfinite(ts):
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text: Optional[str]) -> Optional[float]:
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).timestamp()
    except (ValueError, TypeError):
        return None


def _decompress_payload(data: bytes) -> Optional[bytes]:
    """Try to decompress gzip, zstandard, brotli, or deflate streams."""
    # 1. Gzip
    if GZIP_MAGIC in data:
        pos = data.find(GZIP_MAGIC)
        try:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            decomp = d.decompress(data[pos:])
            if decomp:
                return decomp
        except Exception:
            pass
        try:
            import gzip
            return gzip.decompress(data[pos:])
        except Exception:
            pass

    # 2. Zstandard
    if ZSTD_MAGIC in data:
        pos = data.find(ZSTD_MAGIC)
        # Try Python zstandard module
        try:
            import zstandard
            dctx = zstandard.ZstdDecompressor()
            return dctx.decompress(data[pos:], max_output_size=MAX_CACHE_FILE_SIZE * 10)
        except Exception:
            pass

        # Try external zstd CLI via pipe (in-memory only, no disk writes)
        zstd_bin = shutil.which("zstd")
        if not zstd_bin:
            for candidate in ("/opt/homebrew/bin/zstd", "/usr/local/bin/zstd", "/usr/bin/zstd"):
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    zstd_bin = candidate
                    break
        if zstd_bin:
            try:
                res = subprocess.run(
                    [zstd_bin, "-d", "-c", "-q"],
                    input=data[pos:],
                    capture_output=True,
                    timeout=1,
                    check=False,
                )
                if res.returncode == 0 and res.stdout:
                    return res.stdout
            except Exception:
                pass

    # 3. Brotli
    try:
        import brotli
        return brotli.decompress(data)
    except Exception:
        pass

    # 4. Deflate (zlib)
    try:
        d = zlib.decompressobj()
        decomp = d.decompress(data)
        if decomp:
            return decomp
    except Exception:
        pass

    return None


def _extract_usage_json(raw: bytes) -> Optional[dict]:
    """Find and parse a JSON object in bytes containing five_hour and/or seven_day."""
    if b"five_hour" not in raw and b"seven_day" not in raw:
        return None

    # Fast path: outer braces
    first_brace = raw.find(b"{")
    last_brace = raw.rfind(b"}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            cand = json.loads(raw[first_brace : last_brace + 1].decode("utf-8", errors="replace"))
            if isinstance(cand, dict) and ("five_hour" in cand or "seven_day" in cand):
                return cand
        except Exception:
            pass

    # Slower fallback: search around keyword pos
    pos = raw.find(b"five_hour")
    if pos == -1:
        pos = raw.find(b"seven_day")

    idx = 0
    starts = []
    while idx < pos:
        idx = raw.find(b"{", idx, pos + 1)
        if idx == -1:
            break
        starts.append(idx)
        idx += 1

    for s in starts:
        for e in range(len(raw) - 1, pos, -1):
            if raw[e : e + 1] == b"}":
                try:
                    cand = json.loads(raw[s : e + 1].decode("utf-8"))
                    if isinstance(cand, dict) and ("five_hour" in cand or "seven_day" in cand):
                        return cand
                except Exception:
                    pass

    return None


def _parse_usage_payload(payload: dict, now: float) -> Optional[dict]:
    """Map usage JSON to Kanjo claude quota window dict, filtering expired payloads."""
    if not isinstance(payload, dict):
        return None
    if "usage" in payload and isinstance(payload["usage"], dict):
        payload = payload["usage"]
    elif "data" in payload and isinstance(payload["data"], dict):
        payload = payload["data"]

    seven = payload.get("seven_day") or {}
    five = payload.get("five_hour") or {}
    if not isinstance(seven, dict) and not isinstance(five, dict):
        return None

    seven_reset = _parse_iso(seven.get("resets_at")) if isinstance(seven, dict) else None
    five_reset = _parse_iso(five.get("resets_at")) if isinstance(five, dict) else None

    # Ignore any payload whose resets_at is already in the past (<= now)
    weekly_active = seven_reset is not None and seven_reset > now
    five_active = five_reset is not None and five_reset > now

    if not weekly_active and not five_active:
        return None
    if not weekly_active:
        return None

    sec_pct = _percentage(seven.get("utilization")) if isinstance(seven, dict) else None
    pri_pct = _percentage(five.get("utilization")) if five_active and isinstance(five, dict) else None

    return {
        "weekly_resets_at": _iso_utc(seven_reset),
        "weekly_window_hours": 168,
        "weekly_used_percent": sec_pct,
        "five_hour_resets_at": _iso_utc(five_reset) if five_active else None,
        "five_hour_window_hours": 5,
        "five_hour_used_percent": pri_pct,
        "source": "live",
    }


def scan_claude_desktop_cache(now: float, cache_dir: Optional[str] = None) -> Optional[dict]:
    """Scan Claude Desktop Chromium HTTP cache for recent usage responses.

    Bound by MAX_CACHE_AGE_SECONDS, MAX_CACHE_FILE_SIZE, and MAX_CACHE_FILES_SCANNED.
    Strictly read-only; never raises.
    """
    if not cache_dir:
        cache_dir = os.environ.get("KANJO_CLAUDE_CACHE_DIR")
    if not cache_dir:
        cache_dir = DEFAULT_CLAUDE_CACHE_DIR
    cache_dir = os.path.expanduser(cache_dir)

    try:
        if not os.path.isdir(cache_dir):
            return None
    except OSError:
        return None

    # Cutoff: files modified within the last 7 days (relative to now or current time)
    ref_time = now if now is not None else time.time()
    cutoff = ref_time - MAX_CACHE_AGE_SECONDS

    candidates = []
    try:
        with os.scandir(cache_dir) as it:
            for entry in it:
                if entry.name.startswith(".") or entry.name.startswith("index"):
                    continue
                try:
                    st = entry.stat()
                    if not stat.S_ISREG(st.st_mode):
                        continue
                    if st.st_size <= 0 or st.st_size > MAX_CACHE_FILE_SIZE:
                        continue
                    # Check age: modified within last 7 days of reference time or system time
                    if st.st_mtime < cutoff and st.st_mtime < time.time() - MAX_CACHE_AGE_SECONDS:
                        continue
                    candidates.append((st.st_mtime, entry.path, st.st_size))
                except OSError:
                    continue
    except OSError:
        return None

    # Sort newest-first
    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    candidates = candidates[:MAX_CACHE_FILES_SCANNED]

    for _, path, _ in candidates:
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue

        if not data:
            continue

        # Fast pre-check: must have /usage or five_hour or seven_day or compression magic
        if (
            b"/usage" not in data
            and b"five_hour" not in data
            and b"seven_day" not in data
            and GZIP_MAGIC not in data
            and ZSTD_MAGIC not in data
        ):
            continue

        # Try raw JSON first
        payload = _extract_usage_json(data)
        if not payload:
            decomp = _decompress_payload(data)
            if decomp:
                payload = _extract_usage_json(decomp)

        if payload:
            result = _parse_usage_payload(payload, now=now)
            if result:
                return result

    return None
