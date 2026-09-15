"""Terminal rendering: facts, plan summaries, and evaluation reports."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from gitcrawl.agents.evidence import format_fact
from gitcrawl.collectors.base import Fact
from gitcrawl.plan.models import EvaluationPlan
from gitcrawl.results import EvaluationReport


def render_facts(console: Console, title: str, facts: dict[str, Fact]) -> None:
    """`gitcrawl facts` — deterministic facts only, no model calls."""
    table = Table(title=title, show_lines=True)
    table.add_column("Check", style="bold", no_wrap=True)
    table.add_column("Facts")
    for fact in facts.values():
        body = format_fact(fact).split(": ", 1)[-1]
        style = "red" if not fact.ok else ""
        suffix = " [dim](cached)[/dim]" if fact.cached else ""
        label = escape(fact.check_id)
        if fact.collector != fact.check_id:
            label += f"\n[dim]{escape(fact.collector)}[/dim]"
        table.add_row(
            label,
            f"[{style}]{escape(body)}[/{style}]{suffix}" if style else escape(body) + suffix,
        )
    console.print(table)


def render_plan_summary(console: Console, plan: EvaluationPlan) -> None:
    """`gitcrawl plan` / `plan approve` — what the plan will do, per pillar."""
    table = Table(title=f"Plan — {escape(plan.rubric_title)} (version {escape(plan.rubric_version)})")
    for col, justify in (
        ("Pillar", "left"),
        ("Weight", "right"),
        ("Measured", "right"),
        ("Judgement", "right"),
        ("Not measurable", "right"),
        ("Hard rules", "right"),
    ):
        table.add_column(col, justify=justify)
    for p in plan.pillars:
        count = {
            s: sum(1 for c in p.criteria if c.status == s) for s in ("measured", "judgement", "not_measurable")
        }
        table.add_row(
            escape(p.name),
            f"{p.weight:.0%}",
            str(count["measured"]),
            str(count["judgement"]),
            str(count["not_measurable"]),
            str(len(p.rules)),
        )
    console.print(table)

    console.print(f"\n[bold]Checks[/bold] ({len(plan.checks)}):")
    for c in plan.checks:
        params = f" {c.params}" if c.params else ""
        console.print(f"  {escape(c.id)}: {escape(c.collector)}{escape(params)} [dim]— {escape(c.why)}[/dim]")
    console.print(f"\n[bold]Agents[/bold] ({len(plan.agents)}):")
    for a in plan.agents:
        console.print(f"  {escape(a.id)}: {len(a.task_ids)} question(s), budget {a.budget} tool calls")
    if any(p.rules for p in plan.pillars) or any(
        c.status == "not_measurable" for p in plan.pillars for c in p.criteria
    ):
        console.print("\n[bold]Hard rules and exclusions[/bold]:")
    for p in plan.pillars:
        for r in p.rules:
            action = f"cap {r.cap}" if r.action == "cap" else "not assessed"
            console.print(f"  [yellow]{escape(p.name)} rule:[/yellow] {escape(r.when)} → {action}")
        for c in p.criteria:
            if c.status == "not_measurable":
                console.print(
                    f"  [dim]{escape(p.name)} not measurable: {escape(c.text)} ({escape(c.reason)})[/dim]"
                )
    state = "[green]approved[/green]" if plan.is_approved() else "[yellow]not approved[/yellow]"
    console.print(f"\nStatus: {state}")


def render_evaluation(console: Console, report: EvaluationReport) -> None:
    """`gitcrawl evaluate` — score table, then a few lines of reasoning per pillar."""
    table = Table(title=f"{escape(report.plan_title)} — {escape(report.repo)} @ {report.commit_sha[:10]}")
    table.add_column("Pillar")
    table.add_column("Weight", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Weighted", justify="right")
    for p in report.pillars:
        if p.abstained or p.score is None:
            table.add_row(escape(p.name), f"{p.weight:.0%}", "—", "—")
        else:
            # weight * score, matching clause.md's worked example (see scoring/aggregate.py)
            table.add_row(escape(p.name), f"{p.weight:.0%}", f"{p.score:g}", f"{p.weight * p.score:.2f}")
    console.print(table)

    if report.total_score is not None:
        coverage = f"{report.rubric_coverage:.0%}"
        score = f"{report.total_score:.2f}"
        console.print(f"[bold]Score: {score} / 10[/bold]  ({coverage} of the rubric's weight assessed)")
    else:
        console.print("[bold red]No score — every pillar abstained.[/bold red]")

    for p in report.pillars:
        header = f"\n[bold]{escape(p.name)}[/bold]"
        header += " — [dim]not assessed[/dim]" if p.abstained else f" — {p.score:g}/10"
        if p.cached:
            header += " [dim](cached)[/dim]"
        console.print(header)
        if p.abstained:
            console.print(f"  {escape(p.abstain_reason)}")
        if p.reasoning:
            console.print(f"  {escape(p.reasoning)}")
        for cap in p.caps_applied:
            console.print(f"  [yellow]Hard rule:[/yellow] {escape(cap)}")
        for rule in p.undetermined_rules:
            console.print(f"  [yellow]Hard rule not checked (facts unavailable):[/yellow] {escape(rule)}")
        if p.not_measured:
            console.print(f"  [dim]Not measured: {escape('; '.join(p.not_measured))}[/dim]")
        if p.injection_flagged:
            console.print("  [red]The repository attempted to influence its own evaluation.[/red]")

    s = report.scope
    console.print(
        f"\n[dim]Scope: {s.checks} checks ({s.facts_cached} cached"
        f"{', ' + str(len(s.facts_failed)) + ' unavailable' if s.facts_failed else ''}) · "
        f"agents {s.agents_run} run / {s.agents_cached} cached"
        f"{' / ' + str(len(s.agents_failed)) + ' failed' if s.agents_failed else ''} · "
        f"scorers {s.scorers_run} run / {s.scorers_cached} cached · "
        f"{s.agent_runs} agent runs, {s.tool_calls} tool calls"
        f"{' (+' + str(s.failed_tool_calls) + ' failed)' if s.failed_tool_calls else ''}, "
        f"{s.files_read_by_agents} files read by agents"
        f"{', ' + str(s.unverified_citations) + ' unverified citations' if s.unverified_citations else ''}[/dim]"
    )
