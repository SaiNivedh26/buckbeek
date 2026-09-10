"""Wires every stage together: survey -> budget -> investigate (parallel)
-> cache -> score (parallel) -> cache -> clamp -> aggregate -> Report.
See docs/design.md §2 and §0's eight-step run summary.

This module is the only place that knows the full pipeline order; the CLI
and the public API (__init__.py) both call into it rather than
duplicating the sequence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re

from gitcrawl.agents.investigators import build_investigator
from gitcrawl.agents.rubric import rubric_version
from gitcrawl.agents.scorers import build_scorer
from gitcrawl.budget import allocate_budget
from gitcrawl.config import PILLARS, GitCrawlConfig, get_config
from gitcrawl.models import (
    BudgetLedger,
    Findings,
    InvestigatorOutput,
    PillarVerdict,
    RepoHandle,
    Report,
    RunRecord,
    ScorerOutput,
)
from gitcrawl.scoring.aggregate import aggregate
from gitcrawl.scoring.clamps import apply_clamps
from gitcrawl.source import resolve
from gitcrawl.storage import cache, db
from gitcrawl.survey import run_survey

logger = logging.getLogger(__name__)


def _config_hash(cfg: GitCrawlConfig) -> str:
    payload = json.dumps(cfg.model_dump(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# Providers phrase their wait-time hint differently and there is no
# standard for it: Groq says "Please try again in 1.6125s", Gemini says
# "Please retry in 49.588981056s", others say nothing at all. Matching
# both spellings of the verb is the whole difference between waiting the
# real 49s and retrying after a guessed 8s into the same closed door.
# Anything not covered here just falls back to the flat schedule.
_RETRY_AFTER_RE = re.compile(r"(?:try again|retry) in ([\d.]+)s", re.IGNORECASE)

# Rate limiting is one of the few things that IS standardized across
# providers — HTTP 429 — so check the structured status code first and
# treat message text as a fallback. Message-matching alone is whack-a-mole
# (each provider words it differently, and Gemini's body says
# "RESOURCE_EXHAUSTED" rather than anything containing "rate limit").
def _is_rate_limited(exc_or_text: Exception | str) -> bool:
    status = getattr(exc_or_text, "status_code", None) or getattr(exc_or_text, "code", None)
    if status == 429:
        return True
    text = str(exc_or_text)
    return "429" in text or "rate_limit" in text.lower() or "RESOURCE_EXHAUSTED" in text


# Same check, different name at the call site — content is a plain string
# (Agno's swallowed-error shape), not an exception; the logic is identical.
_is_rate_limited_content = _is_rate_limited


def _retry_delay(exc_or_text: Exception | str, attempt: int, cfg: GitCrawlConfig) -> float:
    """Providers that 429 on a token-per-minute budget (confirmed on Groq)
    tell you exactly how long until it clears — "Please try again in
    1.6125s" — which is far more precise than a guessed backoff schedule
    and lets a request through the moment it's actually allowed rather
    than over- or under-waiting. Falls back to a flat schedule if the
    message doesn't carry one (other providers, or a different error).
    """
    match = _RETRY_AFTER_RE.search(str(exc_or_text))
    if match:
        return float(match.group(1)) + 1.5  # small safety margin
    return cfg.concurrency.retry_base_delay_seconds * attempt


async def _call_agent_with_retry(
    agent_factory, prompt: str, semaphore: asyncio.Semaphore, cfg: GitCrawlConfig
):
    """Runs a fresh agent's arun(prompt) under the shared concurrency
    semaphore, with backoff retries specifically for rate-limit errors —
    confirmed on Groq's free tier (8000 tokens/minute) that running every
    pillar fully in parallel 429s every one of them; see docs/design.md
    §12 and config.toml's [concurrency] section.

    `agent_factory` is called fresh on every attempt rather than reusing
    one Agent instance across retries. Reusing the same instance was a
    real bug: a retry after a partial tool-loop failure carries that
    Agent's accumulated conversation state into the next attempt, and
    live testing showed every retried pillar coming back with ZERO tool
    calls used and no error — the agent wasn't failing, it was confused
    by leftover history from the attempt that got rate-limited mid-loop.

    Rate-limit failures show up in TWO different shapes and both must be
    retried: (a) a raised exception, and (b) — confirmed empirically, and
    the far more common case with Agno — a *successful* arun() whose
    `.content` is a plain string carrying the provider's JSON error body,
    because Agno swallows the underlying SDK error rather than raising it.
    A retry loop keyed on exceptions alone silently never fires for (b).
    """
    max_retries = cfg.concurrency.max_retries_on_rate_limit

    async with semaphore:
        for attempt in range(1, max_retries + 1):
            agent = agent_factory()
            try:
                result = await agent.arun(prompt)
            except Exception as e:
                if _is_rate_limited(e) and attempt < max_retries:
                    await asyncio.sleep(_retry_delay(e, attempt, cfg))
                    continue
                raise

            content = result.content
            if isinstance(content, str) and _is_rate_limited_content(content) and attempt < max_retries:
                await asyncio.sleep(_retry_delay(content, attempt, cfg))
                continue
            return result

        return result  # last attempt's (still rate-limited) result


async def _investigate_pillar(
    pillar: str,
    handle: RepoHandle,
    ledger: BudgetLedger,
    cfg: GitCrawlConfig,
    semaphore: asyncio.Semaphore,
) -> Findings:
    def agent_factory():
        # Rebuilt fresh per retry attempt (see _call_agent_with_retry).
        # Tools are rebound to the same `ledger` each time, so retries
        # still share one real budget rather than each getting a fresh one.
        return build_investigator(pillar, handle, ledger, cfg)

    prompt = (
        f"Investigate the '{pillar}' pillar of the repository at the root directory. "
        "Start with list_directory(\".\") to see what's there, then read whatever is "
        "most relevant to this pillar's brief. Return your Findings when done."
    )
    try:
        result = await _call_agent_with_retry(agent_factory, prompt, semaphore, cfg)
    except Exception:
        # A failed investigation must not crash the run — it degrades to an
        # abstaining Findings — but it must never do so silently. A live
        # run hit exactly this: a config bug (wrong env var name) raised
        # before any API call, got caught here, and every pillar abstained
        # with zero tool calls and NO visible error anywhere — Agno never
        # logs an exception it didn't raise itself. logger.exception is
        # what makes that failure mode impossible to miss next time.
        logger.exception("investigator for pillar=%r failed", pillar)
        return Findings(
            pillar=pillar,
            findings=[],
            evidence_coverage=0.0,
            stopped_reason="error",
            tool_calls_used=ledger.spent.get(pillar, 0),
        )

    content = result.content
    if not isinstance(content, InvestigatorOutput):
        # output_schema should guarantee this; guard anyway rather than
        # trust it silently (docs/design.md §12 flags structured output +
        # tool use as the riskiest assumption in the design).
        return Findings(
            pillar=pillar,
            findings=[],
            evidence_coverage=0.0,
            stopped_reason="error",
            tool_calls_used=ledger.spent.get(pillar, 0),
        )

    # `pillar` and `tool_calls_used` are plumbing (clamp/weight/cache
    # lookups; real spend tracking) — never taken from the model. See
    # InvestigatorOutput's docstring: this used to be one shared schema,
    # and a weaker model filling `tool_calls_used: int` with a list of
    # tool-call descriptions failed validation and discarded an otherwise
    # fine response. Splitting the schema removes the field from what the
    # model is asked to produce at all, rather than just overwriting it
    # after the fact (which was also needed separately for `pillar`,
    # which the model echoed inconsistently — see docs/design.md §15
    # item 5's renormalization test).
    findings = Findings.from_investigator_output(pillar, content, tool_calls_used=ledger.spent.get(pillar, 0))
    if ledger.remaining(pillar) <= 0 and findings.stopped_reason == "confident":
        findings.stopped_reason = "budget_exhausted"
    return findings


async def _score_pillar(
    pillar: str, findings: Findings, cfg: GitCrawlConfig, semaphore: asyncio.Semaphore
) -> PillarVerdict:
    def agent_factory():
        return build_scorer(pillar, cfg)

    prompt = (
        f"FINDINGS FOR PILLAR '{pillar}':\n\n{findings.model_dump_json(indent=2)}\n\n"
        "Score this pillar now."
    )
    try:
        result = await _call_agent_with_retry(agent_factory, prompt, semaphore, cfg)
    except Exception:
        logger.exception("scorer for pillar=%r failed", pillar)
        return PillarVerdict(pillar=pillar, score=None, abstained=True, justification="scorer failed")
    content = result.content
    if not isinstance(content, ScorerOutput):
        return PillarVerdict(
            pillar=pillar, score=None, abstained=True, justification="scorer returned malformed output"
        )
    # `pillar` is code-owned, not model-owned — see ScorerOutput's docstring
    # and the matching comment in _investigate_pillar.
    return PillarVerdict.from_scorer_output(pillar, content)


async def investigate_one(target: str, pillar: str) -> Findings:
    """Public API: run a single pillar's investigator against `target`."""
    cfg = get_config()
    handle = resolve(target)
    survey = run_survey(handle)
    ledger = allocate_budget(survey, cfg)
    semaphore = asyncio.Semaphore(cfg.concurrency.max_concurrent_agent_calls)
    return await _investigate_pillar(pillar, handle, ledger, cfg, semaphore)


async def score_one(findings: Findings) -> PillarVerdict:
    """Public API: score existing Findings. Never touches the repo."""
    cfg = get_config()
    semaphore = asyncio.Semaphore(cfg.concurrency.max_concurrent_agent_calls)
    return await _score_pillar(findings.pillar, findings, cfg, semaphore)


async def evaluate(target: str, only_pillar: str | None = None) -> Report:
    """The full pipeline. See docs/design.md §2 / §0."""
    cfg = get_config()
    provenance: list[RunRecord] = []

    handle = resolve(target)
    provenance.append(RunRecord(stage="access", ok=True, detail=f"commit {handle.commit_sha[:12]}"))

    survey = run_survey(handle)
    provenance.append(
        RunRecord(
            stage="survey",
            ok=True,
            detail=f"{len(survey.candidate_files)} candidates, {survey.excluded_count} excluded",
        )
    )

    ledger = allocate_budget(survey, cfg)
    semaphore = asyncio.Semaphore(cfg.concurrency.max_concurrent_agent_calls)

    pillars = [only_pillar] if only_pillar else list(PILLARS)

    conn = db.connect()
    run_id = cache.create_run(
        conn,
        repo=handle.origin,
        commit_sha=handle.commit_sha,
        rubric_version=cfg.cache.rubric_version,
        config_hash=_config_hash(cfg),
        investigator_model=cfg.models.investigator,
        scorer_model=cfg.models.scorer,
    )

    # --- investigate (parallel), with a cache check per pillar first ---
    async def get_findings(pillar: str) -> Findings:
        cached = cache.load_findings(
            conn,
            commit_sha=handle.commit_sha,
            pillar=pillar,
            tool_version=cfg.cache.tool_version,
            filter_version=cfg.cache.filter_version,
        )
        if cached is not None:
            # A cache hit correctly spends 0 NEW tool calls this run (that
            # part of the scope log — "Budget: N/120" — stays accurate and
            # is in fact the point: proof caching worked). But "examined 0
            # of Y files" would misrepresent a real, prior investigation as
            # if nothing had ever been looked at, so backfill that part
            # from what the cached findings actually recorded.
            cached_findings = cached[1]
            ledger.examined_files += len(cached_findings.files_examined)
            return cached_findings
        return await _investigate_pillar(pillar, handle, ledger, cfg, semaphore)

    findings_list = await asyncio.gather(*(get_findings(p) for p in pillars))

    findings_ids: dict[str, int] = {}
    for pillar, findings in zip(pillars, findings_list, strict=True):
        fid = cache.save_findings(
            conn,
            run_id=run_id,
            commit_sha=handle.commit_sha,
            tool_version=cfg.cache.tool_version,
            filter_version=cfg.cache.filter_version,
            findings=findings,
        )
        findings_ids[pillar] = fid
        cache.save_budget(
            conn,
            run_id=run_id,
            pillar=pillar,
            allocated=ledger.allocated.get(pillar, 0),
            spent=ledger.spent.get(pillar, 0),
            excluded_files=survey.excluded_count,
            examined_files=ledger.examined_files,
        )
    provenance.append(RunRecord(stage="investigate", ok=True, detail=f"{len(pillars)} pillars"))

    # --- score (parallel), with a cache check per pillar first ---
    async def get_verdict(pillar: str, findings: Findings) -> PillarVerdict:
        fid = findings_ids[pillar]
        cached = cache.load_verdict(
            conn, findings_id=fid, rubric_version=cfg.cache.rubric_version, scorer_model=cfg.models.scorer
        )
        if cached is not None:
            return cached
        return await _score_pillar(pillar, findings, cfg, semaphore)

    verdicts = await asyncio.gather(
        *(get_verdict(p, f) for p, f in zip(pillars, findings_list, strict=True))
    )
    verdicts = list(verdicts)

    for pillar, verdict in zip(pillars, verdicts, strict=True):
        cache.save_verdict(
            conn,
            findings_id=findings_ids[pillar],
            rubric_version=cfg.cache.rubric_version,
            scorer_model=cfg.models.scorer,
            verdict=verdict,
        )
    provenance.append(RunRecord(stage="score", ok=True, detail=f"{len(verdicts)} pillars"))

    clamped, clamps_applied = apply_clamps(verdicts, survey, cfg)
    provenance.append(RunRecord(stage="clamps", ok=True, detail=f"{len(clamps_applied)} applied"))

    total_score, coverage = aggregate(clamped, cfg.weights.as_dict())
    cache.finish_run(conn, run_id, total_score, coverage)
    provenance.append(RunRecord(stage="aggregate", ok=True, detail=f"{total_score} @ {coverage:.0%}"))

    conn.close()

    return Report(
        repo=handle.origin,
        commit_sha=handle.commit_sha,
        rubric_version=rubric_version(),
        verdicts=clamped,
        clamps_applied=clamps_applied,
        total_score=total_score,
        rubric_coverage=coverage,
        scope=ledger,
        provenance=provenance,
    )
