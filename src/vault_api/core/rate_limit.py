"""In-process sliding-window rate limiting.

Counters live in this process only: with several workers each keeps its own, so the
effective limit multiplies. A shared store (Redis) can implement `RateLimiter` later.
"""

import math
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

DEFAULT_MAX_TRACKED_KEYS = 50_000
MIN_RETRY_AFTER_SECONDS = 1


@dataclass(frozen=True)
class RateLimit:
    """At most `max_attempts` within any `window_seconds` period.

    Each limit has its own store of at most `max_tracked_keys` keys, so traffic under
    one limit can never evict counters kept for another.
    """

    max_attempts: int
    window_seconds: float
    max_tracked_keys: int = DEFAULT_MAX_TRACKED_KEYS


class RateLimiter(Protocol):
    """Counts attempts per key and limit."""

    def retry_after(self, key: str, limit: RateLimit) -> int | None:
        """Seconds until the next attempt is allowed, or None if it is allowed now."""
        ...

    def record(self, key: str, limit: RateLimit) -> None:
        """Count one attempt for the key."""
        ...

    def reset(self, key: str, limit: RateLimit) -> None:
        """Forget every attempt for the key."""
        ...


class SlidingWindowRateLimiter:
    """Keeps the most recent attempt times per key, in memory with a bounded footprint.

    Per key, only the last `max_attempts` timestamps are kept. Each limit tracks at most
    `max_tracked_keys` keys and evicts the least recently used one beyond that. Both
    checking and recording count as use, so a key under active attack stays tracked
    while unrelated keys are churned.

    Not thread-safe; it is used from the event loop, and no method awaits.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._stores: dict[RateLimit, OrderedDict[str, list[float]]] = {}

    def retry_after(self, key: str, limit: RateLimit) -> int | None:
        attempts = self._recent_attempts(key, limit)
        if attempts is None or len(attempts) < limit.max_attempts:
            return None
        wait = attempts[0] + limit.window_seconds - self._clock()
        return max(MIN_RETRY_AFTER_SECONDS, math.ceil(wait))

    def record(self, key: str, limit: RateLimit) -> None:
        store = self._store(limit)
        attempts = self._recent_attempts(key, limit) or []
        attempts.append(self._clock())
        store[key] = attempts[-limit.max_attempts :]
        store.move_to_end(key)
        while len(store) > limit.max_tracked_keys:
            store.popitem(last=False)

    def reset(self, key: str, limit: RateLimit) -> None:
        self._store(limit).pop(key, None)

    def tracked_keys(self, limit: RateLimit) -> int:
        """Number of keys currently tracked for the limit."""
        return len(self._store(limit))

    def _store(self, limit: RateLimit) -> OrderedDict[str, list[float]]:
        return self._stores.setdefault(limit, OrderedDict())

    def _recent_attempts(self, key: str, limit: RateLimit) -> list[float] | None:
        """The key's attempts inside the window, marking the key as recently used.

        Drops the key once no attempt remains inside the window.
        """
        store = self._store(limit)
        attempts = store.get(key)
        if attempts is None:
            return None
        window_start = self._clock() - limit.window_seconds
        recent = [moment for moment in attempts if moment > window_start]
        if not recent:
            del store[key]
            return None
        store[key] = recent
        store.move_to_end(key)
        return recent
