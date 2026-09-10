"""GitCrawl — agentic GitHub repository quality evaluator.

Public API. Everything the CLI does is reachable here (see docs/design.md §7.1);
the CLI is a thin shell over these four calls.
"""

from __future__ import annotations

from dotenv import find_dotenv, load_dotenv

# Load .env (MISTRAL_API_KEY, and later GITHUB_TOKEN etc.) as soon as the
# package is imported, so both the CLI and a bare `import gitcrawl` pick it
# up without extra ceremony. Searches upward from the current working
# directory (see .env.example); never overrides a variable already set in
# the real environment.
load_dotenv(find_dotenv(usecwd=True), override=False)

from gitcrawl.models import Findings, PillarVerdict, Report, Survey  # noqa: E402

__all__ = [
    "evaluate",
    "survey",
    "investigate",
    "score",
    "Report",
    "Survey",
    "Findings",
    "PillarVerdict",
]


def survey(target: str) -> Survey:
    """Zero-token file inventory and presence flags. No model calls."""
    from gitcrawl.source import resolve
    from gitcrawl.survey import run_survey

    return run_survey(resolve(target))


async def investigate(target: str, pillar: str) -> Findings:
    """Run one pillar's investigator. Does not score."""
    from gitcrawl.orchestrator import investigate_one

    return await investigate_one(target, pillar)


async def score(findings: Findings) -> PillarVerdict:
    """Score existing Findings against the rubric. Never touches the repo."""
    from gitcrawl.orchestrator import score_one

    return await score_one(findings)


async def evaluate(target: str, only_pillar: str | None = None) -> Report:
    """Run the full pipeline: survey -> investigate -> score -> aggregate."""
    from gitcrawl.orchestrator import evaluate as _evaluate

    return await _evaluate(target, only_pillar=only_pillar)
