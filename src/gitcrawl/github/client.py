"""A small async GitHub API client: GraphQL for aggregates and bounded
windows, REST only where GraphQL has no equivalent (Actions runs,
contributors). Responses are memoized per client (one client per run), so
collectors that share a query don't pay for it twice.

Failures raise typed errors — never an error string that could be mistaken
for data. Rate limits honor GitHub's own Retry-After / X-RateLimit-Reset.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from gitcrawl.collectors.base import CollectorError
from gitcrawl.config import GitCrawlConfig

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com"
_MAX_WAIT_SECONDS = 90.0


class GitHubError(CollectorError):
    """Any GitHub API failure. A CollectorError, so a collector that hits one
    reports it as an explicit unavailable fact."""


class GitHubNotFound(GitHubError):
    pass


class GitHubRateLimited(GitHubError):
    pass


class GitHubClient:
    def __init__(
        self,
        token: str,
        cfg: GitCrawlConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._client = httpx.AsyncClient(
            base_url=API_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "gitcrawl",
            },
            timeout=cfg.github.timeout_seconds,
            transport=transport,
        )
        self._max_retries = cfg.github.max_retries
        self._sleep = sleep
        self._memo: dict[str, Any] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self.requests = 0

    async def aclose(self) -> None:
        await self._client.aclose()

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        body = await self._memoized("POST", "/graphql", json={"query": query, "variables": variables})
        if body.get("errors"):
            first = body["errors"][0]
            message = first.get("message", "unknown GraphQL error")
            if first.get("type") == "NOT_FOUND":
                raise GitHubNotFound(f"GitHub: {message}")
            raise GitHubError(f"GitHub GraphQL error: {message}")
        return body["data"]

    async def rest(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return await self._memoized("GET", path, params=params)

    async def _memoized(self, method: str, url: str, **kwargs: Any) -> Any:
        key = json.dumps([method, url, kwargs], sort_keys=True, default=str)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key not in self._memo:
                self._memo[key] = await self._request(method, url, **kwargs)
            return self._memo[key]

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        for attempt in range(1, self._max_retries + 2):
            self.requests += 1
            try:
                resp = await self._client.request(method, url, **kwargs)
            except httpx.HTTPError as e:
                if attempt <= self._max_retries:
                    logger.warning("GitHub %s %s failed (%s), retrying", method, url, e)
                    await self._sleep(2.0 * attempt)
                    continue
                raise GitHubError(f"GitHub request failed: {type(e).__name__}: {e}") from e

            if resp.status_code in (403, 429) and self._is_rate_limited(resp):
                wait = self._rate_limit_wait(resp)
                if attempt > self._max_retries or wait > _MAX_WAIT_SECONDS:
                    raise GitHubRateLimited(
                        f"GitHub API rate limit reached (resets in about {wait:.0f}s) — try again later"
                    )
                logger.warning("GitHub rate limited on %s, waiting %.1fs", url, wait)
                await self._sleep(wait)
                continue
            if resp.status_code >= 500 and attempt <= self._max_retries:
                logger.warning("GitHub %s on %s, retrying", resp.status_code, url)
                await self._sleep(2.0 * attempt)
                continue
            if resp.status_code == 401:
                raise GitHubError("GitHub rejected the token (401) — check GITHUB_TOKEN in .env")
            if resp.status_code == 404:
                raise GitHubNotFound(f"GitHub: not found: {url}")
            if resp.status_code >= 400:
                raise GitHubError(f"GitHub API error {resp.status_code} on {url}: {resp.text[:200]}")
            return resp.json()
        raise GitHubError("unreachable: retry loop exhausted")

    @staticmethod
    def _is_rate_limited(resp: httpx.Response) -> bool:
        return (
            resp.status_code == 429
            or resp.headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in resp.headers
            or "rate limit" in resp.text.lower()
        )

    @staticmethod
    def _rate_limit_wait(resp: httpx.Response) -> float:
        if "retry-after" in resp.headers:
            try:
                return float(resp.headers["retry-after"])
            except ValueError:
                pass
        reset = resp.headers.get("x-ratelimit-reset")
        if reset and reset.isdigit():
            return max(0.0, int(reset) - time.time()) + 1.0
        return 60.0
