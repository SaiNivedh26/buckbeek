"""GitCrawl CLI. Contains no logic — every command is a thin call into the
library (see __init__.py) rendered with rich. See docs/design.md §7.1.
"""

from __future__ import annotations

from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

app = typer.Typer(add_completion=False, no_args_is_help=True)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        try:
            v = _pkg_version("gitcrawl")
        except Exception:
            v = "0.1.0"
        console.print(f"gitcrawl {v}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show the version and exit."),
    ] = False,
) -> None:
    """GitCrawl — agentic GitHub repository quality evaluator."""


@app.command()
def survey(target: Annotated[str, typer.Argument(help="Local path or git URL.")] = ".") -> None:
    """Zero-token file inventory and presence flags. No model calls, no cost."""
    from gitcrawl.report import render_survey
    from gitcrawl.source import resolve
    from gitcrawl.survey import run_survey

    handle = resolve(target)
    result = run_survey(handle)
    render_survey(console, result)


@app.command()
def evaluate(
    target: Annotated[str, typer.Argument(help="Local path or git URL.")] = ".",
    pillar: Annotated[
        str | None, typer.Option(help="Evaluate a single pillar only (for development).")
    ] = None,
    json_out: Annotated[Path | None, typer.Option("--json", help="Write the full report as JSON.")] = None,
) -> None:
    """Run the full evaluation pipeline and print a report."""
    import asyncio

    from gitcrawl.orchestrator import evaluate as run_evaluate
    from gitcrawl.report import render_report

    report = asyncio.run(run_evaluate(target, only_pillar=pillar))
    render_report(console, report)
    if json_out:
        json_out.write_text(report.model_dump_json(indent=2))
        console.print(f"[dim]Wrote {json_out}[/dim]")


if __name__ == "__main__":
    app()
