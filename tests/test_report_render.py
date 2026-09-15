"""The terminal report's Weighted column must use the same formula as
scoring/aggregate.py (weight * score) — a previous renderer used the rubric
prose's weight * score/10, which no aggregate test could catch."""

from rich.console import Console

from gitcrawl.report import render_evaluation
from gitcrawl.results import EvaluationReport, PillarResult, Scope


def _render(report: EvaluationReport) -> str:
    console = Console(file=None, record=True, width=140)
    render_evaluation(console, report)
    return console.export_text()


def test_weighted_column_and_reasoning_render():
    scores = {
        "Code Health": (0.25, 8),
        "Test Coverage": (0.20, 7),
        "CI/CD": (0.20, 9),
        "Issue Management": (0.20, 6),
        "Community": (0.15, 5),
    }
    pillars = [
        PillarResult(
            pillar=name.lower(), name=name, weight=w, score=s, scorer_score=s, reasoning=f"{name} reasoning"
        )
        for name, (w, s) in scores.items()
    ]
    pillars[1] = pillars[1].model_copy(update={"caps_applied": ["lowered 9 → 7: If x, score is at most 7."]})
    pillars[4] = pillars[4].model_copy(update={"not_measured": ["External adoption (no data source)"]})
    report = EvaluationReport(
        repo="acme/widget",
        commit_sha="abc1234567",
        plan_title="Quality",
        plan_version="2.0",
        plan_hash="h",
        total_score=7.15,
        rubric_coverage=1.0,
        pillars=pillars,
        scope=Scope(checks=13),
    )
    text = _render(report)
    for expected in ("2.00", "1.40", "1.80", "1.20", "0.75", "7.15 / 10", "100% of the rubric's weight"):
        assert expected in text, text
    assert "CI/CD reasoning" in text
    assert "Hard rule: lowered 9 → 7" in text
    assert "Not measured: External adoption" in text


def test_abstained_pillar_shows_reason_and_no_score():
    report = EvaluationReport(
        repo="acme/widget",
        commit_sha="abc",
        plan_title="Q",
        plan_version="1",
        plan_hash="h",
        total_score=None,
        rubric_coverage=0.0,
        scope=Scope(),
        pillars=[
            PillarResult(
                pillar="p",
                name="Issues",
                weight=1.0,
                abstained=True,
                abstain_reason="no usable evidence (checks unavailable and no judgement answers)",
            )
        ],
    )
    text = _render(report)
    assert "not assessed" in text and "no usable evidence" in text
    assert "every pillar abstained" in text
