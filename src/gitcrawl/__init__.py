"""GitCrawl — plan-driven GitHub repository quality evaluator.

Public API. Everything the CLI does is reachable here; the CLI is a thin
shell over these calls.

    rubric = load_rubric("my_clause.md")          # or None for the bundled default
    draft = await plan(rubric)                    # one model call; review it
    approved = approve_plan(draft)
    report = await evaluate("owner/repo", approved, rubric)
    facts_only = await facts("owner/repo")        # no model calls
"""

from __future__ import annotations

from dotenv import find_dotenv, load_dotenv

# Load .env (model provider key, GITHUB_TOKEN) as soon as the package is
# imported, so both the CLI and a bare `import gitcrawl` pick it up. Never
# overrides a variable already set in the real environment.
load_dotenv(find_dotenv(usecwd=True), override=False)

from gitcrawl.collectors.base import Fact  # noqa: E402
from gitcrawl.plan.models import EvaluationPlan  # noqa: E402
from gitcrawl.results import EvaluationReport  # noqa: E402
from gitcrawl.rubric import Rubric, load_rubric  # noqa: E402

__all__ = [
    "EvaluationPlan",
    "EvaluationReport",
    "Fact",
    "Rubric",
    "approve_plan",
    "evaluate",
    "facts",
    "load_rubric",
    "plan",
]


async def plan(rubric: Rubric | None = None) -> EvaluationPlan:
    """Draft an Evaluation Plan for a rubric (default: the bundled one). Not approved."""
    from gitcrawl.plan.planner import generate_plan
    from gitcrawl.rubric import load_default_rubric

    return await generate_plan(rubric or load_default_rubric())


def approve_plan(draft: EvaluationPlan) -> EvaluationPlan:
    from gitcrawl.plan.io import approve

    return approve(draft)


async def facts(target: str, plan: EvaluationPlan | None = None) -> dict[str, Fact]:
    """Deterministic facts for a GitHub repository — collectors only, no model calls."""
    from gitcrawl.engine import collect_facts

    _, results, _ = await collect_facts(target, plan.check_requests() if plan else None)
    return results


async def evaluate(
    target: str, plan: EvaluationPlan | None = None, rubric: Rubric | None = None
) -> EvaluationReport:
    """Evaluate a GitHub repository with an approved plan (default: the bundled plan and rubric)."""
    from gitcrawl.engine import evaluate as _evaluate
    from gitcrawl.plan.io import load_default_plan
    from gitcrawl.rubric import load_default_rubric

    return await _evaluate(target, plan or load_default_plan(), rubric or load_default_rubric())
