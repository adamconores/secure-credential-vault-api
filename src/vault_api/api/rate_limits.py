"""Rate limits for the authentication endpoints, as FastAPI dependencies."""

import hashlib
import ipaddress
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from vault_api.core.rate_limit import RateLimit, RateLimiter
from vault_api.models.user import EMAIL_MAX_LENGTH

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 60 * SECONDS_PER_MINUTE

LOGIN_PER_IP = RateLimit(max_attempts=10, window_seconds=SECONDS_PER_MINUTE)
LOGIN_FAILURES_PER_EMAIL = RateLimit(max_attempts=5, window_seconds=15 * SECONDS_PER_MINUTE)
REGISTER_PER_IP = RateLimit(max_attempts=5, window_seconds=SECONDS_PER_HOUR)

UNKNOWN_CLIENT = "unknown"
# One IPv6 subscriber usually controls a whole /64, so counting per address would let
# them rotate through 2**64 keys.
IPV6_CLIENT_PREFIX = 64
TOO_MANY_ATTEMPTS = "Too many attempts; try again later"


def get_rate_limiter(request: Request) -> RateLimiter:
    """The application's limiter, created in `create_app`."""
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def too_many_attempts(retry_after_seconds: int) -> HTTPException:
    """429 with the seconds to wait; the same message for every limit."""
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=TOO_MANY_ATTEMPTS,
        headers={"Retry-After": str(retry_after_seconds)},
    )


def client_key(request: Request) -> str:
    """The client the limits apply to: an IPv4 address, or an IPv6 /64 network.

    The peer address comes from the ASGI server, which decides whether to trust proxy
    headers (`--forwarded-allow-ips`).
    """
    host = request.client.host if request.client else UNKNOWN_CLIENT
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, IPV6_CLIENT_PREFIX), strict=False))
    return str(address)


def email_key(email: str) -> str:
    """Fixed-size key for an email: bounds memory and keeps addresses out of the limiter.

    Input beyond the longest valid email is ignored: such logins cannot succeed anyway.
    """
    normalized = email.strip().lower()[: EMAIL_MAX_LENGTH + 1]
    digest = hashlib.sha256(normalized.encode(errors="replace")).hexdigest()
    return f"login-email:{digest}"


def consume(limiter: RateLimiter, key: str, limit: RateLimit) -> None:
    """Answer 429 if the key is over its limit, otherwise count this attempt.

    Check and count happen with no await in between, so concurrent requests cannot
    all pass the check before any of them is counted.
    """
    retry_after = limiter.retry_after(key, limit)
    if retry_after is not None:
        raise too_many_attempts(retry_after)
    limiter.record(key, limit)


def limit_login_by_ip(request: Request, limiter: RateLimiterDep) -> None:
    """Every login attempt counts against the client IP."""
    consume(limiter, f"login-ip:{client_key(request)}", LOGIN_PER_IP)


def limit_registration_by_ip(request: Request, limiter: RateLimiterDep) -> None:
    """Every registration attempt counts against the client IP."""
    consume(limiter, f"register-ip:{client_key(request)}", REGISTER_PER_IP)
