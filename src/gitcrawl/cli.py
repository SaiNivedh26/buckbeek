"""GitCrawl CLI. Contains no logic — every command is a thin call into the
library, rendered with rich. See docs/design.md §7.1.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()

Target = Annotated[str, typer.Argument(help="GitHub repository: https://github.com/<owner>/<repo> or owner/repo.")]


def _version_callback(value: bool) -> None:
    if value:
        try:
            v = _pkg_version("gitcrawl")
        except Exception:
            v = "0.1.0"
        console.print(f"gitcrawl {v}")
        raise typer.Exit()


def _fail(exc: Exception) -> None:
    console.print(f"[bold red]{escape(str(exc))}[/bold red]")
    raise typer.Exit(code=1)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show the version and exit."),
    ] = False,
) -> None:
    """GitCrawl — plan-driven GitHub repository quality evaluator."""


@app.command()
def plan(
    args: Annotated[
        list[str] | None,
        typer.Argument(help="CLAUSE.md to plan (default: the bundled rubric), or: approve PLAN.yaml"),
    ] = None,
    output: Annotated[Path, typer.Option("--output", "-o", help="Where to write the draft plan.")] = Path(
        "plan.yaml"
    ),
) -> None:
    """Generate a plan from a clause.md for review, or approve a reviewed plan.

    \b
      gitcrawl plan my_clause.md -o my_plan.yaml    # draft (one model call)
      gitcrawl plan approve my_plan.yaml            # after reviewing it
    """
    import asyncio
    import os

    from gitcrawl.plan.io import PlanError, approve, load_plan_and_rubric, write_plan
    from gitcrawl.plan.validate import PlanValidationError, validate_plan
    from gitcrawl.report import render_plan_summary
    from gitcrawl.rubric import RubricError, load_rubric

    args = args or []
    if args and args[0] == "approve":
        if len(args) != 2:
            _fail(ValueError("usage: gitcrawl plan approve PLAN.yaml"))
        try:
            draft, rubric = load_plan_and_rubric(args[1])
        except (PlanError, RubricError) as e:
            _fail(e)
        errors = validate_plan(draft, rubric)
        if errors:
            _fail(PlanValidationError(errors))
        approved = approve(draft)
        write_plan(approved, args[1])
        render_plan_summary(console, approved)
        path = escape(args[1])
        console.print(f"[green]Approved {path}.[/green] Evaluate with: gitcrawl evaluate <repo> --plan {path}")
        return
    if len(args) > 1:
        _fail(ValueError("usage: gitcrawl plan [CLAUSE.md] [-o PLAN.yaml]"))

    from gitcrawl.plan.planner import generate_plan

    clause = Path(args[0]) if args else None
    try:
        rubric = load_rubric(clause)
        rubric_path = os.path.relpath(clause.resolve(), output.resolve().parent) if clause else None
        draft = asyncio.run(generate_plan(rubric, rubric_path=rubric_path))
    except (RubricError, PlanValidationError) as e:
        _fail(e)
    except Exception as e:  # model/provider failures: already logged by the agent runner
        _fail(RuntimeError(f"planning failed: {type(e).__name__}: {e}"))
    write_plan(draft, output)
    render_plan_summary(console, draft)
    path = escape(str(output))
    console.print(f"\nDraft written to [bold]{path}[/bold]. Review it, then run: gitcrawl plan approve {path}")


@app.command()
def facts(
    target: Target,
    plan: Annotated[Path | None, typer.Option(help="Run only this plan's checks.")] = None,
) -> None:
    """Deterministic facts only — collectors, no model calls."""
    import asyncio

    from gitcrawl.engine import collect_facts
    from gitcrawl.plan.io import PlanError, load_plan
    from gitcrawl.report import render_facts
    from gitcrawl.source import SourceError
    from gitcrawl.storage import db

    try:
        requests = load_plan(plan).check_requests() if plan else None
        handle, results, has_token = asyncio.run(collect_facts(target, requests, conn=db.connect()))
    except (PlanError, SourceError) as e:
        _fail(e)
    render_facts(console, f"Facts — {handle.full_name} @ {handle.commit_sha[:10]}", results)
    if not has_token:
        console.print("[yellow]No GITHUB_TOKEN set — GitHub API collectors were unavailable.[/yellow]")


@app.command()
def evaluate(
    target: Target,
    plan: Annotated[Path | None, typer.Option(help="Approved plan file (default: bundled plan).")] = None,
    clause: Annotated[Path | None, typer.Option(help="clause.md the plan was generated from.")] = None,
    json_out: Annotated[Path | None, typer.Option("--json", help="Also write the full report as JSON.")] = None,
) -> None:
    """Evaluate a GitHub repository with an approved plan."""
    import asyncio

    from gitcrawl.engine import PreflightError
    from gitcrawl.engine import evaluate as run_evaluate
    from gitcrawl.plan.io import PlanError, load_plan_and_rubric
    from gitcrawl.report import render_evaluation
    from gitcrawl.rubric import RubricError
    from gitcrawl.source import SourceError
    from gitcrawl.storage import db

    try:
        plan_obj, rubric = load_plan_and_rubric(plan, clause)
        report = asyncio.run(run_evaluate(target, plan_obj, rubric, conn=db.connect()))
    except (PlanError, RubricError, PreflightError, SourceError) as e:
        _fail(e)
    render_evaluation(console, report)
    if json_out:
        json_out.write_text(report.model_dump_json(indent=2))
        console.print(f"[dim]Wrote {json_out}[/dim]")


if __name__ == "__main__":
    app()
