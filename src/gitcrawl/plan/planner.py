"""The planner: one model call that maps a parsed clause.md onto the
collector catalog, producing a draft Evaluation Plan for a person to review.

The model only proposes mappings (which checks, rule expressions, judgement
questions). Code assigns criterion/rule ids, copies names, weights, bands
and text from the parsed rubric, computes agents, and validates everything.
If the draft has problems, the planner gets one more attempt with the exact
validation errors; after that planning fails with those errors instead of
writing a broken plan.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from functools import partial
from typing import Literal

from agno.agent import Agent
from pydantic import BaseModel, Field, ValidationError

from gitcrawl.agents.limiter import limiter_for
from gitcrawl.agents.model_factory import build_model
from gitcrawl.agents.runner import ModelStats, call_agent
from gitcrawl.collectors import REGISTRY
from gitcrawl.collectors.base import catalog_version
from gitcrawl.config import GitCrawlConfig, get_config
from gitcrawl.plan.agents import DOMAIN_TOOLS, compute_agents
from gitcrawl.plan.models import (
    CheckRef,
    CriterionPlan,
    EvaluationPlan,
    EvidenceDomain,
    JudgementTask,
    PillarPlan,
    Rule,
)
from gitcrawl.plan.validate import PlanValidationError, validate_plan
from gitcrawl.rubric.models import Rubric

logger = logging.getLogger(__name__)


class PlannedCheck(BaseModel):
    id: str = Field(description="snake_case id used by criteria, rules and tasks")
    collector: str
    params_json: str = Field(default="{}", description="the collector's parameters as a JSON object")
    why: str = Field(description="one line: which criterion or rule this check serves")


class PlannedCriterion(BaseModel):
    criterion_id: str
    status: Literal["measured", "judgement", "not_measurable"]
    reason: str = ""
    check_ids: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)


class PlannedRule(BaseModel):
    rule_id: str
    when: str
    action: Literal["cap", "abstain"]
    cap: int | None = None


class PlannedTask(BaseModel):
    id: str
    pillar_id: str
    criterion_ids: list[str]
    question: str
    evidence_domain: EvidenceDomain
    check_ids: list[str] = Field(default_factory=list)


class PlannerOutput(BaseModel):
    """Model-owned fields only (see module docstring)."""

    checks: list[PlannedCheck]
    criteria: list[PlannedCriterion]
    rules: list[PlannedRule] = Field(default_factory=list)
    judgement_tasks: list[PlannedTask] = Field(default_factory=list)


DOMAIN_DESCRIPTIONS = {
    "source_code": "reading and judging source code (architecture, coupling, duplication, readability)",
    "tests": "reading test code (are tests meaningful, what do they exercise)",
    "ci": "reading CI configuration and the scripts it runs",
    "issues_prs": "reading GitHub issue and pull request threads (triage, review and discussion quality)",
    "docs_community": "reading README, CHANGELOG, contributing docs and release notes",
}

PLANNER_BRIEF = """\
You turn a repository evaluation rubric into an evaluation plan. You do not evaluate anything.

For EVERY criterion, choose exactly one status:
- "measured": one or more checks from the collector catalog directly answer it. List their ids in \
  check_ids. Prefer this whenever a collector's output fields genuinely answer the criterion.
- "judgement": answering needs a person-like reading of evidence (quality, meaningfulness, clarity). \
  Create a judgement task with one focused question, and list the task id in task_ids. Give the task \
  the check_ids whose facts help answer it, and the evidence_domain that matches what must be read.
- "not_measurable": no collector answers it and no available evidence could (for example adoption in \
  blog posts, or data that needs admin access). Give a one-sentence reason. Never force a weak proxy.
A criterion may use both checks and a task only if it is "judgement" with supporting check_ids.

Checks: each check is one use of a collector with parameters (params_json is a JSON object matching \
the collector's params; use "{}" for collectors without params). Give it a short snake_case id and a \
"why". Reuse one check for several criteria instead of repeating it. Every check must be used.

Hard rules: for EVERY hard rule, write one rule with the given rule_id:
- "when" is an expression over check outputs: check_id.field compared with numbers, true/false, null or \
  strings, combined with and / or / not. Example: tests_inventory.test_file_count == 0. \
  Only fields listed in the catalog exist. No function calls, arithmetic or indexing.
- action "cap" with the stated maximum as cap, or action "abstain" (cap null) for "not assessed" rules.
Add a check if a rule needs facts no criterion uses.

Judgement questions are read by another agent: write them as plain questions. Never write tool calls \
with parentheses in them. Keep tasks few and focused — they cost model calls.

Use only criterion ids, rule ids and pillar ids exactly as given.
"""


def criterion_id(pillar_id: str, index: int) -> str:
    return f"{pillar_id}_{index + 1}"


def rule_id(pillar_id: str, index: int) -> str:
    return f"{pillar_id}_rule_{index + 1}"


def planner_model(cfg: GitCrawlConfig) -> str:
    return cfg.models.planner or cfg.models.scorer


def render_catalog() -> str:
    blocks = []
    for spec in REGISTRY.values():
        params = ", ".join(
            f"{name}: {label}{'' if spec.params_model.model_fields[name].is_required() else ' (optional)'}"
            for name, label in spec.param_fields().items()
        )
        outputs = ", ".join(f"{name}: {label}" for name, label in spec.output_fields().items())
        blocks.append(
            f"- {spec.name}  [{spec.category}{', GitHub API' if spec.requires_github else ''}]\n"
            f"  {spec.description}\n"
            f"  params: {params or 'none'}\n"
            f"  output fields: {outputs}"
        )
    return "\n".join(blocks)


def build_planner_prompt(
    rubric: Rubric, previous: PlannerOutput | None = None, errors: list[str] | None = None
) -> str:
    pillars = []
    for p in rubric.pillars:
        lines = [f"PILLAR {p.id} — {p.name} (weight {p.weight:.0%})"]
        if p.focus:
            lines.append(f"Focus: {p.focus}")
        lines.append("Criteria:")
        lines += [f"  {criterion_id(p.id, i)}: {text}" for i, text in enumerate(p.criteria)]
        if p.hard_rules:
            lines.append("Hard rules:")
            lines += [f"  {rule_id(p.id, i)}: {text}" for i, text in enumerate(p.hard_rules)]
        pillars.append("\n".join(lines))

    domains = "\n".join(f"- {d}: {desc}" for d, desc in DOMAIN_DESCRIPTIONS.items())
    prompt = (
        f"RUBRIC: {rubric.title}\n\n"
        + "\n\n".join(pillars)
        + f"\n\nCOLLECTOR CATALOG:\n{render_catalog()}\n\nEVIDENCE DOMAINS:\n{domains}\n"
    )
    if errors:
        prompt += (
            "\nYOUR PREVIOUS PLAN HAD THESE PROBLEMS — fix every one and return the complete corrected plan:\n"
            + "\n".join(f"- {e}" for e in errors)
            + ("\n\nPREVIOUS PLAN:\n" + previous.model_dump_json() if previous else "")
            + "\n"
        )
    return prompt + "\nProduce the plan now."


def merge_planner_output(
    rubric: Rubric,
    output: PlannerOutput,
    *,
    cfg: GitCrawlConfig,
    model: str,
    rubric_path: str | None = None,
) -> tuple[EvaluationPlan, list[str]]:
    errors: list[str] = []

    checks: list[CheckRef] = []
    for c in output.checks:
        try:
            params = json.loads(c.params_json or "{}")
            if not isinstance(params, dict):
                raise ValueError("not a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            errors.append(f"check {c.id!r}: params_json must be a JSON object ({e})")
            params = {}
        checks.append(CheckRef(id=c.id, collector=c.collector, params=params, why=c.why))

    planned_criteria: dict[str, PlannedCriterion] = {}
    for pc in output.criteria:
        if pc.criterion_id in planned_criteria:
            errors.append(f"criterion {pc.criterion_id!r} was planned twice")
        planned_criteria[pc.criterion_id] = pc
    planned_rules = {r.rule_id: r for r in output.rules}

    pillars: list[PillarPlan] = []
    known_criteria: set[str] = set()
    known_rules: set[str] = set()
    for spec in rubric.pillars:
        criteria: list[CriterionPlan] = []
        for i, text in enumerate(spec.criteria):
            cid = criterion_id(spec.id, i)
            known_criteria.add(cid)
            pc = planned_criteria.get(cid)
            if pc is None:
                errors.append(f"criterion {cid!r} ({text!r}) was not planned")
                criteria.append(CriterionPlan(id=cid, text=text, status="not_measurable", reason="(not planned)"))
                continue
            criteria.append(
                CriterionPlan(
                    id=cid,
                    text=text,
                    status=pc.status,
                    reason=pc.reason,
                    check_ids=pc.check_ids,
                    task_ids=pc.task_ids,
                )
            )
        rules: list[Rule] = []
        for i, source in enumerate(spec.hard_rules):
            rid = rule_id(spec.id, i)
            known_rules.add(rid)
            pr = planned_rules.get(rid)
            if pr is None:
                errors.append(f"hard rule {rid!r} ({source!r}) was not planned")
                continue
            try:
                rules.append(Rule(id=rid, source_text=source, when=pr.when, action=pr.action, cap=pr.cap))
            except ValidationError as e:
                errors.append(f"rule {rid!r}: {e.errors()[0]['msg']}")
        pillars.append(
            PillarPlan(
                id=spec.id,
                name=spec.name,
                weight=spec.weight,
                focus=spec.focus,
                bands=spec.bands,
                criteria=criteria,
                rules=rules,
            )
        )
    errors += [f"unknown criterion id {cid!r}" for cid in planned_criteria if cid not in known_criteria]
    errors += [f"unknown rule id {rid!r}" for rid in planned_rules if rid not in known_rules]

    tasks = [JudgementTask(**t.model_dump()) for t in output.judgement_tasks]
    plan = EvaluationPlan(
        rubric_title=rubric.title,
        rubric_version=rubric.version,
        rubric_hash=rubric.content_hash,
        rubric_path=rubric_path,
        catalog_version=catalog_version(),
        planner_model=model,
        created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        checks=checks,
        pillars=pillars,
        judgement_tasks=tasks,
        agents=compute_agents(tasks, cfg),
    )
    errors += validate_plan(plan, rubric)
    return plan, list(dict.fromkeys(errors))


def build_planner_agent(cfg: GitCrawlConfig) -> Agent:
    return Agent(
        name="planner",
        model=build_model(cfg.models.provider, planner_model(cfg)),
        instructions=[PLANNER_BRIEF],
        output_schema=PlannerOutput,
        markdown=False,
    )


async def generate_plan(
    rubric: Rubric,
    *,
    cfg: GitCrawlConfig | None = None,
    rubric_path: str | None = None,
    max_attempts: int = 2,
) -> EvaluationPlan:
    cfg = cfg or get_config()
    limiter = limiter_for(cfg)
    semaphore = asyncio.Semaphore(1)
    stats = ModelStats()
    previous: PlannerOutput | None = None
    errors: list[str] = []

    for attempt in range(1, max_attempts + 1):
        prompt = build_planner_prompt(rubric, previous, errors)
        result = await call_agent(
            partial(build_planner_agent, cfg), prompt, cfg=cfg, limiter=limiter, semaphore=semaphore, stats=stats
        )
        output = result.content
        if not isinstance(output, PlannerOutput):
            errors = [f"the planner returned {type(output).__name__} instead of a structured plan"]
            previous = None
            logger.warning("planner attempt %d returned no structured plan", attempt)
            continue
        plan, errors = merge_planner_output(
            rubric, output, cfg=cfg, model=planner_model(cfg), rubric_path=rubric_path
        )
        if not errors:
            return plan
        previous = output
        logger.warning("planner attempt %d produced %d problem(s)", attempt, len(errors))

    raise PlanValidationError(errors)


__all__ = ["DOMAIN_TOOLS", "PlannerOutput", "generate_plan", "merge_planner_output"]
