"""In-memory cache used by knowledge graph query tools."""

from __future__ import annotations

import time
from typing import Any, Optional, Tuple


class CacheLayer:
    """Simple in-memory cache interface with TTL helpers."""

    def __init__(self) -> None:
        """Initialize in-memory cache store."""
        self._store: dict[str, tuple[Any, float | None]] = {}

    def get(self, key: str) -> Tuple[bool, Optional[Any], Optional[int]]:
        """Get a value and its remaining TTL.

        Returns:
            Tuple of (hit, value, ttl_remaining_seconds).
        """
        item = self._store.get(key)
        if item is None:
            return False, None, None

        value, expire_time = item
        if expire_time is None:
            return True, value, None
        ttl_remaining = int(expire_time - time.time())
        if ttl_remaining <= 0:
            self._store.pop(key, None)
            return False, None, None
        return True, value, ttl_remaining

    def set(self, key: str, value: Any, ttl_seconds: int) -> bool:
        """Set a value with TTL and return success status."""
        expire_time = None if ttl_seconds <= 0 else (time.time() + float(ttl_seconds))
        self._store[key] = (value, expire_time)
        return True

    def clear(self) -> None:
        """Clear all cached entries."""
        self._store.clear()


CACHE = CacheLayer()
