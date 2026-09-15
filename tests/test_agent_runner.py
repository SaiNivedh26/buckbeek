"""Regression coverage for agents/runner.py — every case here was a live failure.

- Agno doesn't always raise on a provider 429: it can return a *successful*
  run whose .content is the provider's error JSON. Retrying only on
  exceptions never fired for that shape (confirmed live).
- Providers state the wait differently: Groq "try again in Xs", Gemini
  "retry in Xs". Matching one wording meant retrying after a guessed 8s into
  a limit that needed 49s.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from gitcrawl.agents.limiter import RateLimiter
from gitcrawl.agents.runner import AgentCallError, ModelStats, call_agent, is_rate_limited, retry_delay
from gitcrawl.config import get_config


class _Run:
    def __init__(self, content):
        self.content = content


def test_retry_delay_parses_groq_wording():
    exc = Exception("Rate limit reached ... Please try again in 1.6125s. Need more tokens?")
    assert retry_delay(exc, attempt=1, cfg=get_config()) == 1.6125 + 1.5


def test_retry_delay_parses_gemini_wording():
    exc = Exception(
        '{"error": {"code": 429, "message": "Please retry in 49.588981056s.", "status": "RESOURCE_EXHAUSTED"}}'
    )
    assert retry_delay(exc, attempt=1, cfg=get_config()) == 49.588981056 + 1.5


def test_retry_delay_falls_back_to_flat_schedule():
    cfg = get_config()
    assert (
        retry_delay(Exception("connection reset"), attempt=2, cfg=cfg)
        == cfg.concurrency.retry_base_delay_seconds * 2
    )


def test_rate_limit_detection():
    class StatusErr(Exception):
        status_code = 429

    assert is_rate_limited(StatusErr("opaque"))
    assert is_rate_limited('{"error": {"status": "RESOURCE_EXHAUSTED"}}')
    assert not is_rate_limited("everything is fine")


async def _call(outputs):
    runs = iter(outputs)

    async def arun(prompt):
        item = next(runs)
        if isinstance(item, Exception):
            raise item
        return _Run(item)

    built = []

    def factory():
        agent = type("Agent", (), {"arun": staticmethod(arun)})()
        built.append(agent)
        return agent

    stats = ModelStats()
    with patch("gitcrawl.agents.runner.asyncio.sleep", AsyncMock()):
        result = await call_agent(
            factory,
            "prompt",
            cfg=get_config(),
            limiter=RateLimiter(None),
            semaphore=asyncio.Semaphore(1),
            stats=stats,
        )
    return result, built, stats


async def test_rate_limit_returned_as_content_is_retried_with_a_fresh_agent():
    result, built, stats = await _call(['{"error": "rate_limit_exceeded. Please try again in 0.01s"}', "ok"])
    assert result.content == "ok"
    assert len(built) == 2 and built[0] is not built[1]  # never reuse an agent across retries
    assert stats.agent_runs == 2 and stats.rate_limit_retries == 1


async def test_rate_limit_raised_as_exception_is_retried():
    class Err(Exception):
        status_code = 429

    result, _, _ = await _call([Err("slow down"), "ok"])
    assert result.content == "ok"


async def test_non_rate_limit_errors_are_raised_immediately():
    with pytest.raises(ValueError):
        await _call([ValueError("bad schema")])


async def test_persistent_rate_limit_content_raises_instead_of_returning_the_error_as_output():
    attempts = get_config().concurrency.max_retries_on_rate_limit
    with pytest.raises(AgentCallError, match="still rate limited"):
        await _call(["429 RESOURCE_EXHAUSTED"] * attempts)
