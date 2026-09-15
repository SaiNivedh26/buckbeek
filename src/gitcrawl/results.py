"""What an evaluation produces."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from gitcrawl.collectors.base import Fact


class JudgementAnswer(BaseModel):
    task_id: str
    answer: str
    confidence: Literal["low", "medium", "high"]
    citations: list[str] = Field(default_factory=list)
    unverified_citations: list[str] = Field(default_factory=list)


class PillarResult(BaseModel):
    pillar: str
    name: str
    weight: float
    score: float | None = None  # final score, after caps
    scorer_score: int | None = None  # what the scorer chose, before caps
    abstained: bool = False
    abstain_reason: str = ""
    reasoning: str = ""
    caps_applied: list[str] = Field(default_factory=list)
    undetermined_rules: list[str] = Field(default_factory=list)
    not_measured: list[str] = Field(default_factory=list)
    injection_flagged: bool = False
    cached: bool = False


class Scope(BaseModel):
    checks: int = 0
    facts_cached: int = 0
    facts_failed: list[str] = Field(default_factory=list)
    agents_run: int = 0
    agents_cached: int = 0
    agents_failed: list[str] = Field(default_factory=list)
    scorers_run: int = 0
    scorers_cached: int = 0
    agent_runs: int = 0  # model-facing arun calls, retries included
    tool_calls: int = 0
    failed_tool_calls: int = 0
    files_read_by_agents: int = 0
    unverified_citations: int = 0


class EvaluationReport(BaseModel):
    repo: str
    commit_sha: str
    plan_title: str
    plan_version: str
    plan_hash: str
    total_score: float | None
    rubric_coverage: float
    pillars: list[PillarResult]
    scope: Scope
    facts: dict[str, Fact] = Field(default_factory=dict)
    judgements: list[JudgementAnswer] = Field(default_factory=list)
