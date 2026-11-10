"""In-memory thread-safe rate limiter with sliding window."""

import threading
import time
from typing import Dict, List, Optional, Tuple


class RateLimiter:
    """Thread-safe sliding window rate limiter tracking request timestamps per key."""

    def __init__(self, window_seconds: float = 60.0, max_requests: int = 1):
        self.window_seconds = window_seconds
        self.max_requests = max_requests
        self._lock = threading.Lock()
        self._records: Dict[str, List[float]] = {}

    def check_and_record(self, key: str, now: Optional[float] = None) -> Tuple[bool, float]:
        """Check if request is allowed under rate limit, and record it if allowed.
        
        Returns:
            (allowed: bool, retry_after: float)
            If allowed is True, retry_after is 0.0.
            If allowed is False, retry_after is remaining seconds in window.
        """
        if now is None:
            now = time.time()

        with self._lock:
            timestamps = self._records.get(key, [])
            cutoff = now - self.window_seconds
            valid = [t for t in timestamps if t > cutoff]

            if len(valid) >= self.max_requests:
                retry_after = (valid[0] + self.window_seconds) - now
                self._records[key] = valid
                return False, max(0.0, retry_after)

            valid.append(now)
            self._records[key] = valid
            return True, 0.0

    def reset(self) -> None:
        """Clear all rate limit records."""
        with self._lock:
            self._records.clear()
