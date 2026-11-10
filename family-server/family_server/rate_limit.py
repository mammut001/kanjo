"""In-memory rate limiter per token with sliding window."""

import threading
import time
from typing import Dict, Optional, Tuple


class RateLimiter:
    """Thread-safe rate limiter tracking the last allowed timestamp per token hash."""

    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._last_allowed: Dict[str, float] = {}

    def check_and_record(self, token_sha256: str, now: Optional[float] = None) -> Tuple[bool, float]:
        """Check if request is allowed under rate limit, and record it if allowed.
        
        Returns:
            (allowed: bool, retry_after: float)
            If allowed is True, retry_after is 0.0.
            If allowed is False, retry_after is remaining seconds in window.
        """
        if now is None:
            now = time.time()

        with self._lock:
            last = self._last_allowed.get(token_sha256)
            if last is not None:
                elapsed = now - last
                if elapsed < self.window_seconds:
                    retry_after = self.window_seconds - elapsed
                    return False, retry_after

            self._last_allowed[token_sha256] = now
            return True, 0.0

    def reset(self) -> None:
        """Clear all rate limit records."""
        with self._lock:
            self._last_allowed.clear()
