"""Weighted total with abstention renormalization. Weights come from the
plan (i.e. from clause.md), never from config.

Weighted_i = weight_i * score_i (weight_i is a fraction of 1, score_i is
0-10). This matches the bundled rubric's worked example (0.25 * 8 = 2.00),
not the literal prose formula Weight_i * (Score_i/10), which would give 0.20
and contradict its own example. The example is the authority; see
tests/test_aggregate.py.

A pillar with insufficient evidence abstains rather than scoring 0 (which
would drag every repo toward the bottom regardless of quality). Weights
renormalize across the pillars that did score:

    total = (sum of weight_i * score_i, scored pillars only)
            / (sum of weight_i, scored pillars only)
    rubric_coverage = sum of weight_i, scored pillars only
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class Scored(Protocol):
    pillar: str
    score: float | None
    abstained: bool


def aggregate(results: Sequence[Scored], weights: dict[str, float]) -> tuple[float | None, float]:
    """Returns (total_score out of 10, rubric_coverage as a 0-1 fraction).
    total_score is None only when every pillar abstained."""
    scored = [r for r in results if not r.abstained and r.score is not None]
    if not scored:
        return None, 0.0

    scored_weight = sum(weights.get(r.pillar, 0.0) for r in scored)
    if scored_weight <= 0:
        return None, 0.0

    raw = sum(weights.get(r.pillar, 0.0) * r.score for r in scored)
    return round(raw / scored_weight, 2), round(scored_weight, 4)
