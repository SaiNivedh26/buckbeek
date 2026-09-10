"""report.py's per-row 'Weighted' column must use the same formula as
scoring/aggregate.py (weight * score), not the one clause.md's prose
literally states (weight * score/10) — see the comment in both files.
A prior version of report.py used the wrong one, which never failed a
test because test_aggregate.py only ever exercised aggregate.py itself.
"""

from rich.console import Console

from gitcrawl.models import BudgetLedger, PillarVerdict, Report
from gitcrawl.report import render_report


def test_weighted_column_reproduces_clause_md_worked_example():
    report = Report(
        repo="example/repo",
        commit_sha="abc123",
        rubric_version="1.0",
        verdicts=[
            PillarVerdict(pillar="code_health", score=8, confidence=0.9, justification=""),
            PillarVerdict(pillar="test_coverage", score=7, confidence=0.9, justification=""),
            PillarVerdict(pillar="ci_cd", score=9, confidence=0.9, justification=""),
            PillarVerdict(pillar="issue_management", score=6, confidence=0.9, justification=""),
            PillarVerdict(pillar="community", score=5, confidence=0.9, justification=""),
        ],
        total_score=7.15,
        rubric_coverage=1.0,
        scope=BudgetLedger(allocated={"code_health": 10}, spent={"code_health": 2}, total_files=10),
    )

    console = Console(file=None, record=True, width=120)
    render_report(console, report)
    text = console.export_text()

    # clause.md §2.2's worked example weighted-score column, verbatim.
    for expected in ("2.00", "1.40", "1.80", "1.20", "0.75"):
        assert expected in text, f"expected {expected!r} in rendered table:\n{text}"
