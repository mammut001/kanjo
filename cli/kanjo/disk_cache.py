"""Best-effort, atomic cache of the complete disk report."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from typing import Optional

from .cache import _cache_dir


def cache_path() -> str:
    return os.path.join(_cache_dir(), "disk-report.json")


def _scan_time(doc: dict) -> float:
    return datetime.fromisoformat(doc["scanned_at"].replace("Z", "+00:00")).timestamp()


def cache_age(now: Optional[float] = None) -> Optional[float]:
    try:
        with open(cache_path(), encoding="utf-8") as handle:
            payload = json.load(handle)
        return max(0.0, (time.time() if now is None else now) - _scan_time(payload["report"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def load(roots: dict, now: float, max_age: float) -> Optional[dict]:
    if max_age <= 0:
        return None
    try:
        with open(cache_path(), encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload["roots"] != roots:
            return None
        doc = payload["report"]
        scanned = _scan_time(doc)
        # ISO timestamps round to microseconds; tolerate that rounding at age zero.
        if now - scanned < -0.000001 or now - scanned >= max_age or doc["schema_version"] != 1:
            return None
        # Only stat entry roots: never rediscover or walk trees on a cache hit.
        for agent in doc["agents"]:
            for entry in agent["entries"]:
                if os.stat(entry["path"]).st_mtime > scanned:
                    return None
        doc["cached"] = True
        return doc
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def save(doc: dict, roots: dict) -> None:
    path = cache_path()
    tmp = None
    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".disk-report-", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"roots": roots, "report": doc}, handle,
                      ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.replace(tmp, path)
    except OSError:
        pass  # A cache that cannot be written only costs speed.
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def invalidate() -> None:
    try:
        os.unlink(cache_path())
    except OSError:
        pass
