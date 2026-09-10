"""Pydantic contracts shared across GitCrawl's stages. See docs/design.md §8.

Naming follows §0's vocabulary exactly: Findings are an investigator's notes
(no score); a PillarVerdict is a scorer's number. Keeping those two types
distinct is what keeps evidence and judgment separate (§1).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

StoppedReason = Literal["confident", "budget_exhausted", "clamped_early", "error"]


class RepoHandle(BaseModel):
    """Where the repo lives on disk, and what commit it's pinned to."""

    root: str  # absolute local path to the checked-out repo
    origin: str  # original path or URL the user passed
    commit_sha: str
    is_temp_clone: bool = False


class Finding(BaseModel):
    """One observation an investigator made, with the evidence behind it."""

    observation: str
    citations: list[str] = Field(default_factory=list)  # file paths / concrete values


class InvestigatorOutput(BaseModel):
    """What an investigator agent is actually asked to produce as its
    output_schema. Deliberately excludes `pillar` and `tool_calls_used` —
    both are set deterministically by the orchestrator after the call
    returns (see _investigate_pillar), never trusted from the model. A
    live run on a weaker model showed exactly why this split exists:
    asked to fill in `tool_calls_used: int`, it emitted a list of tool
    call descriptions instead of a count, which failed schema validation
    and discarded an otherwise-fine response. Fields the model has no
    business guessing shouldn't be in its schema at all.
    """

    findings: list[Finding] = Field(default_factory=list)
    sub_scores: dict[str, float] = Field(default_factory=dict)  # sub-criteria, 0-10, informational
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    files_examined: list[str] = Field(default_factory=list)
    stopped_reason: StoppedReason = "confident"


class Findings(BaseModel):
    """An investigator's complete output for one pillar. Never carries a
    score. `pillar` and `tool_calls_used` are always set by code, not by
    the model — see InvestigatorOutput.
    """

    pillar: str
    findings: list[Finding] = Field(default_factory=list)
    sub_scores: dict[str, float] = Field(default_factory=dict)  # sub-criteria, 0-10, informational
    evidence_coverage: float = Field(ge=0.0, le=1.0)
    files_examined: list[str] = Field(default_factory=list)
    stopped_reason: StoppedReason = "confident"
    tool_calls_used: int = 0

    @classmethod
    def from_investigator_output(cls, pillar: str, output: InvestigatorOutput, tool_calls_used: int) -> Findings:
        return cls(pillar=pillar, tool_calls_used=tool_calls_used, **output.model_dump())


class ScorerOutput(BaseModel):
    """What a scorer agent is actually asked to produce. Excludes `pillar`
    for the same reason InvestigatorOutput excludes it — see above."""

    score: float | None = Field(default=None, ge=0.0, le=10.0)  # None == abstained
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    justification: str = ""
    abstained: bool = False


class PillarVerdict(BaseModel):
    """A scorer's output: a rubric-band judgment over one pillar's Findings.
    `pillar` is always set by code, not by the model — see ScorerOutput."""

    pillar: str
    score: float | None = Field(default=None, ge=0.0, le=10.0)  # None == abstained
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    justification: str = ""
    abstained: bool = False

    @classmethod
    def from_scorer_output(cls, pillar: str, output: ScorerOutput) -> PillarVerdict:
        return cls(pillar=pillar, **output.model_dump())


class BudgetLedger(BaseModel):
    """Plain-code bookkeeping, never shown to a model. See §5.4."""

    allocated: dict[str, int] = Field(default_factory=dict)
    spent: dict[str, int] = Field(default_factory=dict)
    excluded_files: int = 0
    examined_files: int = 0
    total_files: int = 0

    def remaining(self, pillar: str) -> int:
        return max(0, self.allocated.get(pillar, 0) - self.spent.get(pillar, 0))

    def spend(self, pillar: str, n: int = 1) -> None:
        self.spent[pillar] = self.spent.get(pillar, 0) + n


class Survey(BaseModel):
    """The zero-token pass: file inventory and presence flags. See §5.1."""

    root: str
    commit_sha: str
    total_files: int
    candidate_files: list[str]  # after exclusions, ranked
    excluded_count: int
    has_tests: bool
    has_ci: bool
    has_readme: bool
    has_license: bool
    has_contributing: bool
    has_changelog: bool
    early_clamps: dict[str, float] = Field(default_factory=dict)  # pillar -> max score


class RunRecord(BaseModel):
    """Provenance: which stage did what, and whether it succeeded."""

    stage: str
    ok: bool
    detail: str = ""
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Report(BaseModel):
    """The final, complete output of a run."""

    repo: str
    commit_sha: str
    rubric_version: str
    verdicts: list[PillarVerdict] = Field(default_factory=list)
    clamps_applied: list[str] = Field(default_factory=list)
    total_score: float | None = None
    rubric_coverage: float = 0.0
    scope: BudgetLedger = Field(default_factory=BudgetLedger)
    provenance: list[RunRecord] = Field(default_factory=list)
