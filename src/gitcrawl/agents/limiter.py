"""Per-provider request pacing for free-tier model quotas.

v1 relied on concurrency=1 plus 429 retries plus manual pre-warming. This
spaces requests evenly instead, so a run stays under the provider's
requests-per-minute limit rather than hitting it and backing off. 429 retry
(agents/runner.py) remains as the backstop.

Agno's tool loop makes several model requests inside one `arun`, so pacing
is applied both before each `arun` (async) and before each tool call
(sync, via a tool hook) — each tool call is followed by another model request.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

from gitcrawl.config import GitCrawlConfig


class RateLimiter:
    def __init__(
        self,
        requests_per_minute: float | None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.interval = 60.0 / requests_per_minute if requests_per_minute else 0.0
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()
        self.acquired = 0

    def _reserve(self) -> float:
        with self._lock:
            self.acquired += 1
            now = self._clock()
            start = max(now, self._next)
            self._next = start + self.interval
            return start - now

    async def acquire(self) -> None:
        wait = self._reserve()
        if wait > 0:
            await asyncio.sleep(wait)

    def acquire_sync(self) -> None:
        wait = self._reserve()
        if wait > 0:
            self._sleep(wait)


_LIMITERS: dict[str, RateLimiter] = {}


def limiter_for(cfg: GitCrawlConfig) -> RateLimiter:
    provider = cfg.models.provider
    if provider not in _LIMITERS:
        _LIMITERS[provider] = RateLimiter(cfg.rate_limits.requests_per_minute.get(provider))
    return _LIMITERS[provider]
