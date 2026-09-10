"""Regression coverage for orchestrator.py's pillar-name normalization and
the model/code schema split.

Two live-only bugs, both reproduced offline here so neither can regress
without a live model call:

1. A live run showed the model echoing `pillar` inconsistently ("Test
   Coverage" vs "test_coverage") as part of its own structured output,
   which silently zeroed that pillar's weight in aggregate() with no
   error — the report just quietly dropped a pillar. Fixed by moving
   `pillar` out of the model's schema entirely (InvestigatorOutput /
   ScorerOutput carry no `pillar` field at all) rather than trusting the
   model and overwriting it after — see models.py.

2. A separate live run on a weaker model showed it filling the (then
   model-facing) `tool_calls_used: int` field with a list of tool-call
   descriptions instead of a count, which failed schema validation and
   discarded an otherwise-fine response. Same fix: the field isn't in
   the model's schema at all now.
"""

import asyncio
from unittest.mock import AsyncMock, patch

from gitcrawl.config import get_config
from gitcrawl.models import (
    BudgetLedger,
    Finding,
    Findings,
    InvestigatorOutput,
    PillarVerdict,
    RepoHandle,
    ScorerOutput,
)
from gitcrawl.orchestrator import _investigate_pillar, _score_pillar


class _FakeRunOutput:
    def __init__(self, content):
        self.content = content


async def test_investigator_output_gets_the_canonical_pillar_attached():
    """InvestigatorOutput has no `pillar` field for the model to get wrong
    — the orchestrator attaches the real one when building Findings."""
    model_output = InvestigatorOutput(
        findings=[
            Finding(observation="12 test files, all covering parser.py", citations=["tests/test_parser.py"])
        ],
        evidence_coverage=0.8,
        stopped_reason="confident",
    )
    handle = RepoHandle(root=".", origin=".", commit_sha="abc123")
    ledger = BudgetLedger(allocated={"test_coverage": 10}, spent={"test_coverage": 2})
    cfg = get_config()

    with patch("gitcrawl.orchestrator.build_investigator") as mock_build:
        mock_build.return_value.arun = AsyncMock(return_value=_FakeRunOutput(model_output))
        semaphore = asyncio.Semaphore(cfg.concurrency.max_concurrent_agent_calls)
        result = await _investigate_pillar("test_coverage", handle, ledger, cfg, semaphore)

    assert result.pillar == "test_coverage"
    assert result.evidence_coverage == 0.8
    assert result.findings[0].observation.startswith("12 test files")
    assert result.tool_calls_used == ledger.spent["test_coverage"]  # code-owned, not the model's


async def test_investigator_malformed_output_falls_back_to_error_findings():
    """A response that isn't an InvestigatorOutput at all (e.g. Agno's
    swallowed-error string, or a genuinely malformed parse) must degrade
    to an explicit error Findings, never crash or fabricate content."""
    handle = RepoHandle(root=".", origin=".", commit_sha="abc123")
    ledger = BudgetLedger(allocated={"test_coverage": 10}, spent={"test_coverage": 1})
    cfg = get_config()

    with patch("gitcrawl.orchestrator.build_investigator") as mock_build:
        mock_build.return_value.arun = AsyncMock(return_value=_FakeRunOutput("not a valid schema instance"))
        semaphore = asyncio.Semaphore(cfg.concurrency.max_concurrent_agent_calls)
        result = await _investigate_pillar("test_coverage", handle, ledger, cfg, semaphore)

    assert result.pillar == "test_coverage"
    assert result.stopped_reason == "error"
    assert result.evidence_coverage == 0.0


async def test_scorer_output_gets_the_canonical_pillar_attached():
    findings = Findings(pillar="test_coverage", findings=[], evidence_coverage=0.8, stopped_reason="confident")
    model_output = ScorerOutput(score=3.0, confidence=0.9, justification="low coverage")
    cfg = get_config()

    with patch("gitcrawl.orchestrator.build_scorer") as mock_build:
        mock_build.return_value.arun = AsyncMock(return_value=_FakeRunOutput(model_output))
        semaphore = asyncio.Semaphore(cfg.concurrency.max_concurrent_agent_calls)
        result = await _score_pillar("test_coverage", findings, cfg, semaphore)

    assert result.pillar == "test_coverage"
    assert result.score == 3.0
    assert result.justification == "low coverage"


async def test_a_pillar_name_mismatch_would_have_zeroed_its_weight():
    """Documents the exact failure mode the fix above prevents: aggregate()
    looks scores up by exact pillar string, so any mismatch silently
    drops that pillar's weight to 0 rather than raising."""
    from gitcrawl.scoring.aggregate import aggregate

    weights = {"test_coverage": 0.20, "code_health": 0.25}
    mismatched = [PillarVerdict(pillar="Test Coverage", score=8.0, confidence=0.9, justification="")]
    total, coverage = aggregate(mismatched, weights)
    assert total is None  # confirms the silent-drop mechanism, pre-fix
    assert coverage == 0.0


def test_retry_delay_parses_exact_wait_from_groq_error():
    from gitcrawl.orchestrator import _retry_delay

    cfg = get_config()
    exc = Exception(
        "Error code: 429 - {'error': {'message': 'Rate limit reached for model "
        "`openai/gpt-oss-120b` ... on tokens per minute (TPM): Limit 8000, Used 5927, "
        "Requested 2288. Please try again in 1.6125s. Need more tokens?', "
        "'type': 'tokens', 'code': 'rate_limit_exceeded'}}"
    )
    delay = _retry_delay(exc, attempt=1, cfg=cfg)
    assert delay == 1.6125 + 1.5


def test_retry_delay_falls_back_when_no_wait_time_present():
    from gitcrawl.orchestrator import _retry_delay

    cfg = get_config()
    exc = Exception("connection reset")
    delay = _retry_delay(exc, attempt=2, cfg=cfg)
    assert delay == cfg.concurrency.retry_base_delay_seconds * 2


async def test_retry_detects_rate_limit_returned_as_content_not_exception():
    """The actual failure mode hit in live testing: Agno doesn't raise on a
    provider 429 — it returns a *successful* RunOutput whose .content is a
    plain string carrying the error JSON. A retry loop keyed only on
    caught exceptions never fires for this (confirmed live: zero
    exceptions were ever raised while every pillar failed this way).
    """
    import asyncio

    from gitcrawl.orchestrator import _call_agent_with_retry

    rate_limited_content = (
        '{"error":{"message":"Rate limit reached ... Please try again in 0.01s.",'
        '"type":"tokens","code":"rate_limit_exceeded"}}'
    )
    good_content = Findings(pillar="test_coverage", findings=[], evidence_coverage=0.9, stopped_reason="confident")

    call_count = 0

    async def fake_arun(prompt):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _FakeRunOutput(rate_limited_content)
        return _FakeRunOutput(good_content)

    fake_agent = type("FakeAgent", (), {"arun": staticmethod(fake_arun)})()
    cfg = get_config()
    semaphore = asyncio.Semaphore(cfg.concurrency.max_concurrent_agent_calls)

    result = await _call_agent_with_retry(lambda: fake_agent, "prompt", semaphore, cfg)

    assert call_count == 2  # retried exactly once, then succeeded
    assert result.content == good_content


def test_retry_delay_parses_gemini_phrasing():
    """Gemini says "Please retry in Xs"; Groq says "Please try again in Xs".
    Matching only one wording meant falling back to a flat 8s schedule
    against a limit that actually needed 49s — retrying straight into the
    same closed door, repeatedly, until the retry budget ran out."""
    from gitcrawl.orchestrator import _retry_delay

    cfg = get_config()
    exc = Exception(
        '{"error": {"code": 429, "message": "You exceeded your current quota ... '
        'Please retry in 49.588981056s.", "status": "RESOURCE_EXHAUSTED"}}'
    )
    assert _retry_delay(exc, attempt=1, cfg=cfg) == 49.588981056 + 1.5


def test_rate_limit_detected_by_status_code_not_just_text():
    """HTTP 429 is the one part of this that IS standardized — prefer the
    structured status code over matching prose."""
    from gitcrawl.orchestrator import _is_rate_limited

    class FakeErr(Exception):
        status_code = 429

    assert _is_rate_limited(FakeErr("something opaque with no useful words"))


def test_gemini_resource_exhausted_body_is_detected():
    from gitcrawl.orchestrator import _is_rate_limited

    assert _is_rate_limited('{"error": {"status": "RESOURCE_EXHAUSTED"}}')
