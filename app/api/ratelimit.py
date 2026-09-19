# Per-IP rate limiting for the endpoints that cost money

# /visualize and /plan each call the Anthropic API, so a public demo URL is a way for
# anyone with the link to spend the owner's credits. This caps how often one caller can
# do that. /health and /capabilities are free to serve and are not limited.

# It is a sliding window kept in memory, which means it resets on restart and is per
# process. That is the right size of solution for a demo link. Anything serious would
# need Redis so the limit holds across restarts and multiple workers.

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import Request

from app.errors import CtgovVizError


class RateLimitedError(CtgovVizError):
    # Raised when a caller has used up their allowance for the window

    code = "rate_limited"


class SlidingWindowLimiter:
    # Tracks recent request times per key and refuses once the window is full

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> tuple[bool, int]:
        # Returns (allowed, seconds until the oldest hit falls out of the window)
        now = time.time()
        hits = self._hits[key]

        # Drop anything older than the window before counting.
        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.limit:
            retry_after = int(hits[0] + self.window_seconds - now) + 1
            return False, max(retry_after, 1)

        hits.append(now)

        # Keys that stopped being used would otherwise pile up forever.
        if len(self._hits) > 10_000:
            self._prune(cutoff)
        return True, 0

    def _prune(self, cutoff: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]
        for k in stale:
            del self._hits[k]

    def reset(self) -> None:
        # Used by tests
        self._hits.clear()


def client_key(request: Request) -> str:
    # Work out who is calling.
    # Render and most hosts put the real client IP in X-Forwarded-For and their own proxy
    # IP in request.client, so without this every caller would share one bucket. The
    # header is trivially spoofable, which is fine here: this is a spend guard against
    # casual traffic, not a security control.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(request: Request) -> None:
    # FastAPI dependency. Attached only to the endpoints that call the Anthropic API.
    settings = request.app.state.settings
    if not settings.rate_limit_enabled:
        return

    limiter: SlidingWindowLimiter = request.app.state.rate_limiter
    allowed, retry_after = limiter.check(client_key(request))
    if not allowed:
        raise RateLimitedError(
            f"Rate limit reached: {settings.rate_limit_per_hour} questions per hour per "
            "client. This demo runs on a personal API key, so usage is capped.",
            remedy=f"Try again in about {retry_after // 60 + 1} minute(s), or run the "
            "service locally where the limit can be raised or turned off.",
        )
