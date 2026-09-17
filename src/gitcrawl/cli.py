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
from rich.panel import Panel
from rich.table import Table

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


@app.command("submit")
def submit_command(
    endpoint: Annotated[str, typer.Option(envvar="GITCRAWL_ENDPOINT", help="Authenticated control API URL.")],
    directory: Annotated[Path, typer.Argument(help="Repository directory to upload.")] = Path("."),
    json_output: Annotated[
        bool, typer.Option("--json", help="Print machine-readable JSON and disable interactive progress.")
    ] = False,
    tui: Annotated[
        bool, typer.Option("--tui/--no-tui", help="Use the live terminal dashboard when stdout is interactive.")
    ] = True,
) -> None:
    """Upload a repository and wait for its tailored hosted evaluation."""
    from gitcrawl.hosted.client import submit, validate_endpoint
    from gitcrawl.hosted.tui import HostedSubmitTUI

    try:
        endpoint = validate_endpoint(endpoint)
    except ValueError as exc:
        _fail(exc)

    dashboard = HostedSubmitTUI(console) if tui and not json_output and console.is_terminal else None
    last_plain_phase = None
    last_upload_bucket = -1
    downloaded_path = None

    if dashboard is not None:
        dashboard.start()

    def event(kind: str, value: dict) -> None:
        nonlocal downloaded_path, last_plain_phase, last_upload_bucket
        if json_output:
            return
        if dashboard is not None:
            dashboard.update(kind, value)
            if kind == "download":
                downloaded_path = value.get("path")
            return
        if kind == "agent_id_added":
            console.print(f"[green]✓[/green] Added Agent-ID {value['agent_id']} to {value['path']}")
            return
        if kind == "archive":
            console.print(f"[green]✓[/green] Archived {value['files']:,} files ({value['size']:,} bytes)")
            return
        if kind == "download":
            downloaded_path = value["path"]
            console.print(f"[green]✓[/green] Downloaded eval.md -> {value['path']}")
            return
        if kind == "upload":
            percent = int(100 * value["sent"] / max(value["total"], 1))
            bucket = percent // 25
            if bucket > last_upload_bucket:
                console.print(
                    f"[cyan]↑[/cyan] upload: {percent:>3}% "
                    f"({value['sent']:,}/{value['total']:,} bytes)"
                )
                last_upload_bucket = bucket
            return
        if kind == "submission":
            console.print(f"[dim]Submission {value['submission_id']}[/dim]")
            return
        if kind == "phase":
            phase = value.get("phase") or value.get("status")
            description = value.get("message") or str(phase).replace("_", " ").title()
            if phase != last_plain_phase:
                console.print(f"[cyan]→[/cyan] {phase}: {description}")
                last_plain_phase = phase

    try:
        try:
            cli_version = _pkg_version("gitcrawl")
        except Exception:
            cli_version = "0.1.0"
        result = submit(directory, endpoint, cli_version=cli_version, on_event=event)
    except Exception as exc:
        if dashboard is not None:
            dashboard.fail(str(exc))
        _fail(exc)
    if dashboard is not None:
        dashboard.complete(result)
    if json_output:
        console.print_json(data=result)
        return

    evaluation = result.get("evaluation") or {}
    summary = Table.grid(padding=(0, 2))
    summary.add_column(style="bold cyan")
    summary.add_column()
    summary.add_row("Submission", str(result.get("submission_id", "unknown")))
    summary.add_row("Agent", str(result.get("agent_id", "unknown")))
    summary.add_row("Revision", str(result.get("revision", "unknown")))
    summary.add_row("Eval hash", str(result.get("active_eval_hash", "unknown"))[:16])
    score = evaluation.get("total_score")
    summary.add_row("Score", "not assessed" if score is None else f"[bold green]{score:.2f}/10[/bold green]")
    summary.add_row("Deployment", "created" if result.get("deployed") else "reused")
    console.print(
        Panel(
            summary,
            title="[bold green]✓ GitCrawl analysis complete[/bold green]",
            border_style="green",
        )
    )
    if downloaded_path:
        console.print(f"[green]✓[/green] Downloaded eval.md -> {downloaded_path}")


if __name__ == "__main__":
    app()
