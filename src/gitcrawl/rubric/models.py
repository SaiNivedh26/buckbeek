"""Parsed-rubric contracts. Every field here comes from the template by
plain parsing, never from a model — a misread weight or band would silently
skew every score, so these stay code-owned end to end.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RubricError(Exception):
    """clause.md doesn't follow the template. Carries every problem found,
    not just the first, so a user can fix the file in one pass."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("clause.md is invalid:\n" + "\n".join(f"  - {e}" for e in errors))


class Band(BaseModel):
    low: int = Field(ge=0, le=10)
    high: int = Field(ge=0, le=10)
    text: str

    def contains(self, score: float) -> bool:
        return self.low <= score <= self.high


class PillarSpec(BaseModel):
    id: str  # slug derived from name, e.g. "ci_cd"
    name: str
    weight: float  # fraction of 1, e.g. 0.25
    focus: str = ""
    criteria: list[str]
    bands: list[Band]
    hard_rules: list[str] = Field(default_factory=list)


class Rubric(BaseModel):
    title: str
    version: str
    pillars: list[PillarSpec]
    content_hash: str

    def pillar(self, pillar_id: str) -> PillarSpec:
        for p in self.pillars:
            if p.id == pillar_id:
                return p
        raise KeyError(pillar_id)

    def weights(self) -> dict[str, float]:
        return {p.id: p.weight for p in self.pillars}
