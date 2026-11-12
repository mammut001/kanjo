"""Best-effort, atomic cache of the complete disk report."""

from __future__ import annotations

import json
import os
import tempfile
import time
from datetime import datetime
from typing import Optional

from . import winsupport
from .cache import _cache_dir


def cache_path() -> str:
    return os.path.join(_cache_dir(), "disk-report.json")


# ``scanned_at`` is written as ISO 8601 with microsecond resolution, while the
# clock that stamps it advances in coarser ticks (``time.time()`` only moves every
# ~15.6 ms on Windows, NTFS stores 100 ns). A file written in the same tick can
# therefore carry an mtime fractionally newer than the boundary, and would be
# mistaken for an edit. 50 ms is below the smallest real edit these caches track
# and well under the 1 s deltas the invalidation tests use.
#
# Windows only: the coarse clock tick is what makes it necessary there. POSIX
# hosts keep the exact ``st_mtime <= scanned`` comparison they have always had, so
# their cache decisions do not change at all.
_SIG_TOLERANCE_WINDOWS = 0.05


def _sig_tolerance() -> float:
    """How much an mtime may exceed ``scanned_at`` and still count as unchanged."""
    return _SIG_TOLERANCE_WINDOWS if winsupport.is_windows() else 0.0


def _scan_time(doc: dict) -> float:
    return datetime.fromisoformat(doc["scanned_at"].replace("Z", "+00:00")).timestamp()


def cache_age(now: Optional[float] = None) -> Optional[float]:
    try:
        with open(cache_path(), encoding="utf-8") as handle:
            payload = json.load(handle)
        return max(0.0, (time.time() if now is None else now) - _scan_time(payload["report"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def load_cached_report(roots: dict, now: float, max_age: float) -> Tuple[Optional[dict], Dict[str, dict], dict]:
    """Return (full_hit_doc, valid_entries_by_id, worktree_dirty_cache)."""
    if max_age <= 0:
        return None, {}, {}
    try:
        with open(cache_path(), encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("roots") != roots:
            return None, {}, {}
        doc = payload.get("report")
        if not isinstance(doc, dict):
            return None, {}, {}
        scanned = _scan_time(doc)
        if now - scanned < -0.000001 or now - scanned >= max_age or doc.get("schema_version") != 1:
            return None, {}, {}
        worktrees = payload.get("worktrees") or {}
        valid_entries = {}
        all_valid = True
        # Zero off Windows, so POSIX keeps the exact comparison.
        tolerance = _sig_tolerance()
        for agent in doc.get("agents", []):
            for entry in agent.get("entries", []):
                p = entry.get("path")
                try:
                    st = os.stat(p)
                    # A coarse clock tick can leave a directory's mtime fractionally
                    # past the boundary (Windows); anything newer is a real edit.
                    if st.st_mtime <= scanned + tolerance:
                        valid_entries[entry["id"]] = entry
                    else:
                        all_valid = False
                except OSError:
                    all_valid = False
        if all_valid and len(valid_entries) > 0:
            doc["cached"] = True
            return doc, valid_entries, worktrees
        return None, valid_entries, worktrees
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, {}, {}


def load(roots: dict, now: float, max_age: float) -> Optional[dict]:
    doc, _, _ = load_cached_report(roots, now, max_age)
    return doc


def save(doc: dict, roots: dict, worktrees: Optional[dict] = None) -> None:
    path = cache_path()
    tmp = None
    try:
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".disk-report-", dir=directory)
        payload = {"roots": roots, "report": doc, "worktrees": worktrees or {}}
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.write("\n")
        del data
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
