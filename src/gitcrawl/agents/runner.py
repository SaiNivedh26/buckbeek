"""Running an Agno agent reliably on free-tier providers: pacing, 429
retries in both of their shapes, and a fresh agent per attempt.

Rate-limit failures show up in TWO shapes and both must be retried: a raised
exception, and — confirmed live, the more common case with Agno — a
*successful* `arun()` whose `.content` is a plain string carrying the
provider's JSON error body. A retry loop keyed on exceptions alone silently
never fires for the second.

`agent_factory` is called fresh on every attempt: reusing one Agent across
retries carried stale conversation state into the next attempt and produced
confused, zero-tool-call output with no error raised.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from gitcrawl.agents.limiter import RateLimiter
from gitcrawl.config import GitCrawlConfig

# Providers phrase the wait hint differently: Groq "Please try again in
# 1.6125s", Gemini "Please retry in 49.58s". Extend this, don't assume one wording.
_RETRY_AFTER_RE = re.compile(r"(?:try again|retry) in ([\d.]+)s", re.IGNORECASE)


def is_rate_limited(exc_or_text: Exception | str) -> bool:
    status = getattr(exc_or_text, "status_code", None) or getattr(exc_or_text, "code", None)
    if status == 429:
        return True
    text = str(exc_or_text)
    return "429" in text or "rate_limit" in text.lower() or "RESOURCE_EXHAUSTED" in text


def retry_delay(exc_or_text: Exception | str, attempt: int, cfg: GitCrawlConfig) -> float:
    match = _RETRY_AFTER_RE.search(str(exc_or_text))
    if match:
        return float(match.group(1)) + 1.5
    return cfg.concurrency.retry_base_delay_seconds * attempt


@dataclass
class ModelStats:
    agent_runs: int = 0
    rate_limit_retries: int = 0


class AgentCallError(Exception):
    pass


async def call_agent(
    agent_factory,
    prompt: str,
    *,
    cfg: GitCrawlConfig,
    limiter: RateLimiter,
    semaphore: asyncio.Semaphore,
    stats: ModelStats,
):
    max_retries = cfg.concurrency.max_retries_on_rate_limit
    async with semaphore:
        for attempt in range(1, max_retries + 1):
            await limiter.acquire()
            agent = agent_factory()
            stats.agent_runs += 1
            try:
                result = await agent.arun(prompt)
            except Exception as e:
                if is_rate_limited(e) and attempt < max_retries:
                    stats.rate_limit_retries += 1
                    await asyncio.sleep(retry_delay(e, attempt, cfg))
                    continue
                raise
            content = result.content
            if isinstance(content, str) and is_rate_limited(content):
                if attempt < max_retries:
                    stats.rate_limit_retries += 1
                    await asyncio.sleep(retry_delay(content, attempt, cfg))
                    continue
                raise AgentCallError(f"still rate limited after {max_retries} attempts: {content[:200]}")
            return result
    raise AgentCallError("unreachable: retry loop exited without a result")
