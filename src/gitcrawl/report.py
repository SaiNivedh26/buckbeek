"""Rendering — rich terminal output, plus (later, step 10) markdown/JSON and
the scope log. See docs/design.md §5.6 and §7.5.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from gitcrawl.models import Report, Survey


def render_survey(console: Console, survey: Survey) -> None:
    """`gitcrawl survey` output — zero-token, no scores, just what's there."""
    table = Table(title=f"Survey — {survey.root}", show_lines=False)
    table.add_column("Signal", style="bold")
    table.add_column("Value")

    table.add_row("Commit", survey.commit_sha[:12])
    table.add_row("Total files seen", str(survey.total_files))
    table.add_row("Excluded (vendored/generated/binary)", str(survey.excluded_count))
    table.add_row("Candidate shortlist size", str(len(survey.candidate_files)))
    table.add_row("Has tests", _yn(survey.has_tests))
    table.add_row("Has CI", _yn(survey.has_ci))
    table.add_row("Has README", _yn(survey.has_readme))
    table.add_row("Has LICENSE", _yn(survey.has_license))
    table.add_row("Has CONTRIBUTING", _yn(survey.has_contributing))
    table.add_row("Has CHANGELOG", _yn(survey.has_changelog))
    console.print(table)

    if survey.early_clamps:
        console.print("\n[bold yellow]Early clamps[/bold yellow] (fired before any model call):")
        for pillar, cap in survey.early_clamps.items():
            console.print(f"  {pillar} ≤ {cap:g}")
    else:
        console.print("\n[dim]No early clamps fired.[/dim]")


def _yn(value: bool) -> str:
    return "[green]yes[/green]" if value else "[red]no[/red]"


def render_report(console: Console, report: Report) -> None:
    """`gitcrawl evaluate` output — full pillar table + scope log. Built out
    in step 10 once the orchestrator produces a real Report."""
    weights = {
        "code_health": 0.25,
        "test_coverage": 0.20,
        "ci_cd": 0.20,
        "issue_management": 0.20,
        "community": 0.15,
    }
    names = {
        "code_health": "Code Health",
        "test_coverage": "Test Coverage",
        "ci_cd": "CI/CD",
        "issue_management": "Issue Management",
        "community": "Community",
    }

    table = Table(title=f"GitCrawl — {report.repo}")
    table.add_column("Pillar")
    table.add_column("Weight", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Weighted", justify="right")
    table.add_column("Notes")

    for verdict in report.verdicts:
        weight = weights.get(verdict.pillar, 0.0)
        name = names.get(verdict.pillar, verdict.pillar)
        if verdict.abstained or verdict.score is None:
            table.add_row(name, f"{weight:.0%}", "—", "—", "[dim]not assessed[/dim]")
        else:
            # weight * score, not weight * (score/10) — see
            # scoring/aggregate.py's module docstring: clause.md's own
            # worked example (§2.2: 0.25 * 8 = 2.00) only holds with this
            # formula, not the one literally written in its prose.
            weighted = weight * verdict.score
            note = verdict.justification[:60]
            table.add_row(name, f"{weight:.0%}", f"{verdict.score:g}", f"{weighted:.2f}", note)

    console.print(table)

    if report.total_score is not None:
        console.print(
            f"\n[bold]Repository Quality Score: {report.total_score:.2f} / 10[/bold]"
            f"  ({report.rubric_coverage:.0%} rubric coverage)"
        )
    else:
        console.print("\n[bold red]No score — every pillar abstained.[/bold red]")

    if report.clamps_applied:
        console.print("\n[yellow]Clamps applied:[/yellow]")
        for c in report.clamps_applied:
            console.print(f"  {c}")

    console.print("\n[dim]Scope decisions[/dim]")
    console.print(
        f"  Examined {report.scope.examined_files} of {report.scope.total_files} files"
        f" ({report.scope.excluded_files} excluded as vendored/generated)"
    )
    total_alloc = sum(report.scope.allocated.values()) or 1
    total_spent = sum(report.scope.spent.values())
    console.print(f"  Budget: {total_spent} / {total_alloc} tool calls used")
