import pytest
from conftest import FakeClock

from vault_api.core.rate_limit import RateLimit, SlidingWindowRateLimiter

THREE_PER_MINUTE = RateLimit(max_attempts=3, window_seconds=60)


@pytest.fixture
def limiter(clock: FakeClock) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(clock=clock)


def record_times(limiter: SlidingWindowRateLimiter, key: str, count: int) -> None:
    for _ in range(count):
        limiter.record(key, THREE_PER_MINUTE)


def test_attempts_under_the_limit_are_allowed(limiter: SlidingWindowRateLimiter) -> None:
    record_times(limiter, "k", THREE_PER_MINUTE.max_attempts - 1)

    assert limiter.retry_after("k", THREE_PER_MINUTE) is None


def test_reaching_the_limit_blocks_until_the_oldest_attempt_expires(
    limiter: SlidingWindowRateLimiter, clock: FakeClock
) -> None:
    limiter.record("k", THREE_PER_MINUTE)
    clock.advance(10)
    record_times(limiter, "k", 2)

    # The oldest attempt was 10 s ago, so it leaves the 60 s window in 50 s.
    assert limiter.retry_after("k", THREE_PER_MINUTE) == 50

    clock.advance(49.5)
    assert limiter.retry_after("k", THREE_PER_MINUTE) == 1

    clock.advance(0.5)
    assert limiter.retry_after("k", THREE_PER_MINUTE) is None


def test_window_slides_rather_than_resetting(
    limiter: SlidingWindowRateLimiter, clock: FakeClock
) -> None:
    for _ in range(THREE_PER_MINUTE.max_attempts):
        limiter.record("k", THREE_PER_MINUTE)
        clock.advance(20)

    # The first attempt has just left the window; the other two are still inside it.
    limiter.record("k", THREE_PER_MINUTE)
    assert limiter.retry_after("k", THREE_PER_MINUTE) == 20


def test_keys_are_independent(limiter: SlidingWindowRateLimiter) -> None:
    record_times(limiter, "a", THREE_PER_MINUTE.max_attempts)

    assert limiter.retry_after("a", THREE_PER_MINUTE) is not None
    assert limiter.retry_after("b", THREE_PER_MINUTE) is None


def test_reset_forgets_a_key(limiter: SlidingWindowRateLimiter) -> None:
    record_times(limiter, "k", THREE_PER_MINUTE.max_attempts)

    limiter.reset("k", THREE_PER_MINUTE)

    assert limiter.retry_after("k", THREE_PER_MINUTE) is None


def test_least_recently_used_key_is_evicted_at_capacity(clock: FakeClock) -> None:
    limit = RateLimit(max_attempts=3, window_seconds=60, max_tracked_keys=2)
    limiter = SlidingWindowRateLimiter(clock=clock)
    for key in ("old", "middle"):
        for _ in range(limit.max_attempts):
            limiter.record(key, limit)
    limiter.record("old", limit)  # touching "old" makes "middle" the stalest

    limiter.record("new", limit)

    assert limiter.retry_after("old", limit) is not None
    assert limiter.retry_after("middle", limit) is None


def test_expired_keys_are_dropped(limiter: SlidingWindowRateLimiter, clock: FakeClock) -> None:
    limiter.record("k", THREE_PER_MINUTE)
    clock.advance(THREE_PER_MINUTE.window_seconds)

    assert limiter.retry_after("k", THREE_PER_MINUTE) is None
    assert limiter.tracked_keys(THREE_PER_MINUTE) == 0


def test_one_namespace_cannot_evict_another(clock: FakeClock) -> None:
    small = RateLimit(max_attempts=1, window_seconds=60, max_tracked_keys=2)
    limiter = SlidingWindowRateLimiter(clock=clock)
    limiter.record("victim", THREE_PER_MINUTE)
    record_times(limiter, "victim", THREE_PER_MINUTE.max_attempts - 1)

    for n in range(10):
        limiter.record(f"churn-{n}", small)

    assert limiter.retry_after("victim", THREE_PER_MINUTE) is not None


def test_checking_a_blocked_key_protects_it_from_eviction(clock: FakeClock) -> None:
    limit = RateLimit(max_attempts=1, window_seconds=60, max_tracked_keys=2)
    limiter = SlidingWindowRateLimiter(clock=clock)
    limiter.record("victim", limit)
    limiter.record("other", limit)

    assert limiter.retry_after("victim", limit) is not None  # attacker probes the victim
    limiter.record("churn", limit)

    assert limiter.retry_after("victim", limit) is not None
