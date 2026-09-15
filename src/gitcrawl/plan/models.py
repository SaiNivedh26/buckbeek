"""Evaluation Plan contracts.

Ownership (the v1 "code owns plumbing fields" lesson, applied to plans):
  - copied from the parsed rubric by code: pillar ids/names, weights, bands,
    criterion text, hard-rule source text;
  - proposed by the planner model: which checks measure a criterion, the rule
    expression for each hard rule, judgement questions and their evidence domain;
  - computed by code: agent grouping, tools and budgets, content hash.
Every model-proposed part is validated (plan/validate.py) before a plan is written.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

from gitcrawl.collectors.base import CheckRequest
from gitcrawl.rubric.models import Band

EvidenceDomain = Literal["source_code", "tests", "ci", "issues_prs", "docs_community"]
EVIDENCE_DOMAINS: tuple[str, ...] = get_args(EvidenceDomain)

CriterionStatus = Literal["measured", "judgement", "not_measurable"]
PLAN_FORMAT = 1


class CheckRef(BaseModel):
    id: str  # referenced by criteria and rules, e.g. "has_security_policy"
    collector: str
    params: dict[str, Any] = Field(default_factory=dict)
    why: str = ""


class CriterionPlan(BaseModel):
    id: str
    text: str
    status: CriterionStatus
    reason: str = ""  # required for not_measurable
    check_ids: list[str] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)


class Rule(BaseModel):
    id: str
    source_text: str  # the clause.md hard rule, verbatim
    when: str  # rule expression over check facts, e.g. "tests.file_count == 0"
    action: Literal["cap", "abstain"]
    cap: int | None = Field(default=None, ge=0, le=10)


class JudgementTask(BaseModel):
    id: str
    pillar_id: str
    criterion_ids: list[str]
    question: str
    evidence_domain: EvidenceDomain
    check_ids: list[str] = Field(default_factory=list)  # facts shown to the agent


class AgentSpec(BaseModel):
    id: str
    evidence_domain: EvidenceDomain
    task_ids: list[str]
    tools: list[str]
    budget: int


class PillarPlan(BaseModel):
    id: str
    name: str
    weight: float
    focus: str = ""
    bands: list[Band]
    criteria: list[CriterionPlan]
    rules: list[Rule] = Field(default_factory=list)

    def check_ids(self, plan: EvaluationPlan) -> list[str]:
        """Every check this pillar's criteria, rules and tasks rely on."""
        from gitcrawl.plan.rules import references

        ids: list[str] = []
        for c in self.criteria:
            ids.extend(c.check_ids)
        for r in self.rules:
            ids.extend(ref for ref, _field in references(r.when))
        for t in plan.judgement_tasks:
            if t.pillar_id == self.id:
                ids.extend(t.check_ids)
        return list(dict.fromkeys(ids))


class EvaluationPlan(BaseModel):
    plan_format: int = PLAN_FORMAT
    rubric_title: str
    rubric_version: str
    rubric_hash: str
    # Where the clause.md lives, relative to the plan file (None = bundled default).
    rubric_path: str | None = None
    catalog_version: str
    planner_model: str
    created_at: str
    approved: bool = False
    approved_hash: str | None = None
    checks: list[CheckRef]
    pillars: list[PillarPlan]
    judgement_tasks: list[JudgementTask] = Field(default_factory=list)
    agents: list[AgentSpec] = Field(default_factory=list)

    def content_hash(self) -> str:
        """Hash of everything that affects evaluation — approval metadata excluded,
        so editing anything that matters invalidates an approval."""
        payload = self.model_dump(mode="json", exclude={"approved", "approved_hash", "created_at", "rubric_path"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]

    def is_approved(self) -> bool:
        return self.approved and self.approved_hash == self.content_hash()

    def check(self, check_id: str) -> CheckRef:
        for c in self.checks:
            if c.id == check_id:
                return c
        raise KeyError(check_id)

    def task(self, task_id: str) -> JudgementTask:
        for t in self.judgement_tasks:
            if t.id == task_id:
                return t
        raise KeyError(task_id)

    def pillar(self, pillar_id: str) -> PillarPlan:
        for p in self.pillars:
            if p.id == pillar_id:
                return p
        raise KeyError(pillar_id)

    def check_requests(self) -> list[CheckRequest]:
        return [CheckRequest(id=c.id, collector=c.collector, params=c.params) for c in self.checks]
