"""Executes an approved Evaluation Plan against one GitHub repository.

    preflight (code) -> collectors (code) -> hard rules (code) -> judgement agents
    -> pillar scorers -> caps + abstention + aggregation (code) -> EvaluationReport

This module is the only place that knows the full order. What it guarantees:
  - nothing runs on an unapproved, edited-after-approval or invalid plan;
  - hard rules are evaluated by code; an abstain rule skips that pillar's
    agents and scorer entirely, a cap is enforced after the scorer answers;
  - a pillar with no usable evidence abstains by code, not by prompt;
  - every agent/scorer failure is logged and degrades to an explicit
    abstention or missing answer — and is never cached;
  - citations are checked against what agents actually read.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from functools import partial

from gitcrawl.agents.judge import (
    JUDGE_BRIEF,
    JudgementOutput,
    build_judge_agent,
    build_judge_prompt,
    verify_answers,
)
from gitcrawl.agents.limiter import RateLimiter, limiter_for
from gitcrawl.agents.pillar_scorer import SCORER_BRIEF, ScoreOutput, build_pillar_scorer, build_scorer_prompt
from gitcrawl.agents.runner import ModelStats, call_agent
from gitcrawl.collectors import (
    REGISTRY,
    CheckRequest,
    CollectorContext,
    Fact,
    RepoFiles,
    collect,
    default_requests,
)
from gitcrawl.config import GitCrawlConfig, get_config
from gitcrawl.github import TOKEN_HELP, get_token
from gitcrawl.models import BudgetLedger, RepoHandle
from gitcrawl.plan import rules
from gitcrawl.plan.agents import GITHUB_TOOLS
from gitcrawl.plan.models import EvaluationPlan, PillarPlan
from gitcrawl.plan.validate import validate_plan
from gitcrawl.results import EvaluationReport, JudgementAnswer, PillarResult, Scope
from gitcrawl.rubric.models import Rubric
from gitcrawl.scoring.aggregate import aggregate

logger = logging.getLogger(__name__)


class PreflightError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("cannot evaluate:\n" + "\n".join(f"  - {e}" for e in errors))


def plan_needs_github(plan: EvaluationPlan) -> bool:
    uses_collector = any(c.collector in REGISTRY and REGISTRY[c.collector].requires_github for c in plan.checks)
    uses_tools = any(t in GITHUB_TOOLS for a in plan.agents for t in a.tools)
    return uses_collector or uses_tools


def preflight(plan: EvaluationPlan, rubric: Rubric, *, github_available: bool) -> list[str]:
    errors: list[str] = []
    if not plan.approved:
        errors.append("the plan is not approved — review it, then run `gitcrawl plan approve <plan file>`")
    elif not plan.is_approved():
        errors.append(
            "the plan was edited after it was approved — review the changes, then run "
            "`gitcrawl plan approve <plan file>` again"
        )
    errors.extend(validate_plan(plan, rubric))
    if plan_needs_github(plan) and not github_available:
        errors.append(TOKEN_HELP)
    return errors


def _hash(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:24]


@dataclass
class _RuleOutcome:
    caps: list[tuple[int, str]] = field(default_factory=list)
    abstain: str | None = None
    undetermined: list[str] = field(default_factory=list)


def _evaluate_rules(pillar: PillarPlan, facts: dict[str, Fact]) -> _RuleOutcome:
    out = _RuleOutcome()
    for rule in pillar.rules:
        fired = rules.evaluate(rule.when, facts)
        if fired is None:
            out.undetermined.append(rule.source_text)
        elif fired and rule.action == "abstain":
            out.abstain = rule.source_text
        elif fired and rule.cap is not None:
            out.caps.append((rule.cap, rule.source_text))
    return out


def _has_usable_evidence(pillar: PillarPlan, facts: dict[str, Fact], answers: dict[str, JudgementAnswer]) -> bool:
    for c in pillar.criteria:
        if c.status == "measured" and any(cid in facts and facts[cid].ok for cid in c.check_ids):
            return True
        if c.status == "judgement" and any(tid in answers for tid in c.task_ids):
            return True
    return False


async def collect_facts(
    target: str,
    requests: list[CheckRequest] | None = None,
    *,
    cfg: GitCrawlConfig | None = None,
    conn=None,
) -> tuple[RepoHandle, dict[str, Fact], bool]:
    """Collectors only, no model calls: (handle, facts, whether a GitHub token was available).
    With no requests, runs every built-in collector that needs no parameters."""
    from gitcrawl.source import resolve

    cfg = cfg or get_config()
    handle = resolve(target)
    token = get_token()
    github = None
    if token is not None:
        from gitcrawl.github.client import GitHubClient

        github = GitHubClient(token, cfg)
    try:
        ctx = CollectorContext(
            handle=handle, cfg=cfg, files=RepoFiles(handle.root, cfg.budget.max_file_bytes), github=github
        )
        results = await collect(requests or default_requests(), ctx, conn=conn)
    finally:
        if github is not None:
            await github.aclose()
    return handle, results, token is not None


async def evaluate(
    target: str,
    plan: EvaluationPlan,
    rubric: Rubric,
    *,
    cfg: GitCrawlConfig | None = None,
    conn=None,
) -> EvaluationReport:
    """Full evaluation of a GitHub repository. Preflight runs before anything is cloned."""
    cfg = cfg or get_config()
    needs_github = plan_needs_github(plan)
    token = get_token() if needs_github else None
    errors = preflight(plan, rubric, github_available=token is not None or not needs_github)
    if errors:
        raise PreflightError(errors)

    from gitcrawl.source import resolve

    handle = resolve(target)
    github = None
    if token is not None:
        from gitcrawl.github.client import GitHubClient

        github = GitHubClient(token, cfg)
    try:
        return await evaluate_handle(handle, plan, cfg=cfg, conn=conn, github=github)
    finally:
        if github is not None:
            await github.aclose()


async def evaluate_handle(
    handle: RepoHandle,
    plan: EvaluationPlan,
    *,
    cfg: GitCrawlConfig | None = None,
    conn=None,
    github=None,
    limiter: RateLimiter | None = None,
) -> EvaluationReport:
    from gitcrawl.storage import cache

    cfg = cfg or get_config()
    limiter = limiter or limiter_for(cfg)

    # --- 1. deterministic facts --------------------------------------------
    files = RepoFiles(handle.root, cfg.budget.max_file_bytes)
    ctx = CollectorContext(handle=handle, cfg=cfg, files=files, github=github)
    facts = await collect(plan.check_requests(), ctx, conn=conn)
    scope = Scope(
        checks=len(facts),
        facts_cached=sum(f.cached for f in facts.values()),
        facts_failed=[f.check_id for f in facts.values() if not f.ok],
    )

    # --- 2. hard rules (code) ---------------------------------------------
    outcomes = {p.id: _evaluate_rules(p, facts) for p in plan.pillars}
    active = {p.id for p in plan.pillars if outcomes[p.id].abstain is None}

    # --- 3. judgement agents, one per evidence domain ------------------------
    ledger = BudgetLedger(
        allocated={a.id: a.budget for a in plan.agents},
        spent={a.id: 0 for a in plan.agents},
    )
    stats = ModelStats()
    semaphore = asyncio.Semaphore(cfg.concurrency.max_concurrent_agent_calls)
    answers: dict[str, JudgementAnswer] = {}
    injection_tasks: set[str] = set()

    for agent in plan.agents:
        task_ids = [t for t in agent.task_ids if plan.task(t).pillar_id in active]
        if not task_ids:
            continue
        spec = agent.model_copy(update={"task_ids": task_ids})
        prompt = build_judge_prompt(spec, plan, facts)
        key = {
            "kind": "judgement",
            "repo": handle.full_name,
            "commit_sha": handle.commit_sha,
            "owner_id": spec.id,
            "input_hash": _hash(JUDGE_BRIEF, prompt, spec.model_dump_json()),
            "model": cfg.models.investigator,
        }
        cached = cache.load_model_output(conn, **key) if conn is not None else None
        if cached is not None:
            scope.agents_cached += 1
            for a in cached["answers"]:
                answers[a["task_id"]] = JudgementAnswer(**a)
            if cached.get("injection"):
                injection_tasks.update(task_ids)
            continue

        try:
            result = await call_agent(
                partial(build_judge_agent, spec, handle, ledger, cfg, limiter, github),
                prompt,
                cfg=cfg,
                limiter=limiter,
                semaphore=semaphore,
                stats=stats,
            )
            output = result.content
            if not isinstance(output, JudgementOutput):
                raise TypeError(f"agent returned {type(output).__name__}, not JudgementOutput")
        except Exception:
            # Degrade to "no answers" for these tasks — logged, never silent, never cached.
            logger.exception("judgement agent %s failed", spec.id)
            scope.agents_failed.append(spec.id)
            continue

        scope.agents_run += 1
        verified, missing = verify_answers(output, spec, plan, facts, ledger.read_paths.get(spec.id, []))
        answers.update(verified)
        if output.repository_attempted_injection:
            injection_tasks.update(task_ids)
        if missing:
            logger.warning("judgement agent %s left tasks unanswered: %s", spec.id, missing)
        elif conn is not None:
            cache.save_model_output(
                conn,
                **key,
                payload={
                    "answers": [a.model_dump() for a in verified.values()],
                    "injection": output.repository_attempted_injection,
                },
            )

    # --- 4. pillar scorers + code-owned decisions ---------------------------
    results: list[PillarResult] = []
    for pillar in plan.pillars:
        oc = outcomes[pillar.id]
        base = {
            "pillar": pillar.id,
            "name": pillar.name,
            "weight": pillar.weight,
            "undetermined_rules": oc.undetermined,
            "not_measured": [f"{c.text} ({c.reason})" for c in pillar.criteria if c.status == "not_measurable"],
            "injection_flagged": any(
                t.pillar_id == pillar.id and t.id in injection_tasks for t in plan.judgement_tasks
            ),
        }
        if oc.abstain is not None:
            results.append(PillarResult(**base, abstained=True, abstain_reason=f"hard rule: {oc.abstain}"))
            continue
        if not _has_usable_evidence(pillar, facts, answers):
            results.append(
                PillarResult(
                    **base,
                    abstained=True,
                    abstain_reason="no usable evidence (checks unavailable and no judgement answers)",
                )
            )
            continue

        cap_rule = min(oc.caps, default=None)
        cap = cap_rule[0] if cap_rule else None
        prompt = build_scorer_prompt(pillar, plan, facts, answers, cap)
        key = {
            "kind": "score",
            "repo": handle.full_name,
            "commit_sha": handle.commit_sha,
            "owner_id": pillar.id,
            "input_hash": _hash(SCORER_BRIEF, prompt),
            "model": cfg.models.scorer,
        }
        cached = cache.load_model_output(conn, **key) if conn is not None else None
        from_cache = cached is not None
        if from_cache:
            scope.scorers_cached += 1
            output = ScoreOutput(**cached)
        else:
            try:
                result = await call_agent(
                    partial(build_pillar_scorer, cfg),
                    prompt,
                    cfg=cfg,
                    limiter=limiter,
                    semaphore=semaphore,
                    stats=stats,
                )
                output = result.content
                if not isinstance(output, ScoreOutput):
                    raise TypeError(f"scorer returned {type(output).__name__}, not ScoreOutput")
            except Exception:
                logger.exception("scorer for pillar %s failed", pillar.id)
                results.append(
                    PillarResult(**base, abstained=True, abstain_reason="scorer failed (see log); not cached")
                )
                continue
            scope.scorers_run += 1
            if conn is not None:
                cache.save_model_output(conn, **key, payload=output.model_dump())

        final = float(output.score)
        caps_applied: list[str] = []
        if cap_rule is not None:
            if output.score > cap_rule[0]:
                final = float(cap_rule[0])
                caps_applied.append(f"lowered {output.score} → {cap_rule[0]}: {cap_rule[1]}")
            else:
                caps_applied.append(f"limit {cap_rule[0]} (not exceeded): {cap_rule[1]}")
        results.append(
            PillarResult(
                **base,
                score=final,
                scorer_score=output.score,
                reasoning=output.reasoning,
                caps_applied=caps_applied,
                cached=from_cache,
            )
        )

    total, coverage = aggregate(results, {p.id: p.weight for p in plan.pillars})

    scope.agent_runs = stats.agent_runs
    scope.tool_calls = sum(ledger.spent.values())
    scope.failed_tool_calls = sum(ledger.failed_calls.values())
    scope.files_read_by_agents = len({p for paths in ledger.read_paths.values() for p in paths})
    scope.unverified_citations = sum(len(a.unverified_citations) for a in answers.values())

    return EvaluationReport(
        repo=handle.full_name,
        commit_sha=handle.commit_sha,
        plan_title=plan.rubric_title,
        plan_version=plan.rubric_version,
        plan_hash=plan.content_hash(),
        total_score=total,
        rubric_coverage=coverage,
        pillars=results,
        scope=scope,
        facts=facts,
        judgements=list(answers.values()),
    )
