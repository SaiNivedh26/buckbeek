"""Deterministic bounds applied after scoring, from countable facts. See
docs/design.md §4 "Clamps" — a model can be talked into a good score by a
confident README, so a countable fact overrides it.

Clamps fire twice in a run: once in survey.py (§5.1, before any agent
runs, to cancel wasted investigation), and again here (§4, after scoring)
as the final, authoritative bound — a scorer is never trusted to have
honored the survey's clamp on its own.
"""

from __future__ import annotations

from gitcrawl.config import GitCrawlConfig
from gitcrawl.models import PillarVerdict, Survey

CLAMP_REASONS: dict[str, str] = {
    "test_coverage": "no test files found",
    "ci_cd": "no CI workflow files found",
    "community": "no README and no LICENSE found",
}


def apply_clamps(
    verdicts: list[PillarVerdict], survey: Survey, cfg: GitCrawlConfig
) -> tuple[list[PillarVerdict], list[str]]:
    """Returns (possibly-modified verdicts, human-readable clamp log lines).
    A clamp only ever lowers a score, never raises one, and never applies
    to an abstained pillar (there is no score to bound)."""
    bounds: dict[str, float] = {}
    if not survey.has_tests:
        bounds["test_coverage"] = cfg.clamps.no_tests_max
    if not survey.has_ci:
        bounds["ci_cd"] = cfg.clamps.no_ci_max
    if not survey.has_readme and not survey.has_license:
        bounds["community"] = cfg.clamps.no_readme_no_license_max

    applied: list[str] = []
    clamped: list[PillarVerdict] = []
    for v in verdicts:
        cap = bounds.get(v.pillar)
        if cap is not None and not v.abstained and v.score is not None and v.score > cap:
            reason = CLAMP_REASONS.get(v.pillar, "clamp condition met")
            applied.append(f"{v.pillar}: {v.score:g} -> {cap:g} ({reason})")
            v = v.model_copy(update={"score": cap})
        clamped.append(v)

    return clamped, applied
