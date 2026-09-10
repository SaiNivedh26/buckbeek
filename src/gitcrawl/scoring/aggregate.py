"""clause.md §2.2 arithmetic, plus abstention renormalization. See
docs/design.md §4 "Aggregation" / "Abstention".

Weighted_i = weight_i * score_i (weight_i is a fraction of 1, score_i is
0-10 — this matches clause.md §2.2's own worked example exactly: 0.25 * 8
= 2.00, not clause.md's literally-stated Weight_i * (Score_i/10), which
would give 0.20. The worked example is the authority; see test_aggregate.py).

A pillar with insufficient evidence abstains rather than scoring 0 (which
would drag every repo toward ~4/10 regardless of quality — see docs/design.md
§4). Weights renormalize across the pillars that did score:

    total = (sum of weight_i * score_i, scored pillars only)
            / (sum of weight_i, scored pillars only)
    rubric_coverage = sum of weight_i, scored pillars only
"""

from __future__ import annotations

from gitcrawl.models import PillarVerdict


def aggregate(verdicts: list[PillarVerdict], weights: dict[str, float]) -> tuple[float | None, float]:
    """Returns (total_score out of 10, rubric_coverage as a 0-1 fraction).
    total_score is None only when every pillar abstained."""
    scored = [v for v in verdicts if not v.abstained and v.score is not None]
    if not scored:
        return None, 0.0

    scored_weight = sum(weights.get(v.pillar, 0.0) for v in scored)
    if scored_weight <= 0:
        return None, 0.0

    raw = sum(weights.get(v.pillar, 0.0) * v.score for v in scored)
    total = raw / scored_weight
    return round(total, 2), round(scored_weight, 4)
