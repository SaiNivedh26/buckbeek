"""The budget ledger: allocation, metering, exhaustion. See docs/design.md
5.4. Plain code, per pillar, enforced at the tool layer — never shown to a
model.
"""

from __future__ import annotations

from gitcrawl.config import PILLARS, GitCrawlConfig
from gitcrawl.models import BudgetLedger, Survey

# Phase 1 has no GitHub API tools, so Issue Management can never do more
# than record why it's abstaining. Phase 3 removes this entry once those
# tools exist — see docs/design.md §14.
PHASE1_NO_TOOLING_PILLARS: frozenset[str] = frozenset({"issue_management"})


def allocate_budget(survey: Survey, cfg: GitCrawlConfig) -> BudgetLedger:
    """Split cfg.budget.total_tool_calls across the five pillars,
    proportional to weight * headroom. A pillar that's already clamped (by
    the survey) or has no tools available this phase gets only
    confirmation_calls — enough to double-check the survey's read, or to
    record why it's abstaining, no more.
    """
    confirmation = cfg.budget.confirmation_calls
    weights = cfg.weights.as_dict()

    fixed_pillars = set(survey.early_clamps) | PHASE1_NO_TOOLING_PILLARS
    flexible_pillars = [p for p in PILLARS if p not in fixed_pillars]

    allocated: dict[str, int] = {}
    for p in fixed_pillars:
        if p in PILLARS:
            allocated[p] = confirmation

    reserved = confirmation * len(fixed_pillars)
    remaining = max(0, cfg.budget.total_tool_calls - reserved)
    total_flex_weight = sum(weights[p] for p in flexible_pillars) or 1.0

    for p in flexible_pillars:
        share = remaining * (weights[p] / total_flex_weight)
        allocated[p] = max(confirmation, round(share))

    return BudgetLedger(
        allocated=allocated,
        spent=dict.fromkeys(PILLARS, 0),
        excluded_files=survey.excluded_count,
        examined_files=0,
        total_files=survey.total_files,
    )
