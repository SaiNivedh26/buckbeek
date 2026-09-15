"""Plan files: YAML on disk, approval stamping, and the bundled default plan."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import yaml
from pydantic import ValidationError

from gitcrawl.plan.models import EvaluationPlan


class PlanError(Exception):
    pass


_HEADER = """\
# GitCrawl Evaluation Plan
#
# Generated from a clause.md. Review it before approving:
#   - checks:           deterministic collectors and their parameters ("why" says what each is for)
#   - pillars.criteria: how each criterion is evaluated — measured (checks), judgement (an agent
#                       question), or not_measurable (excluded from the score, with a reason)
#   - pillars.rules:    the clause.md hard rules as checkable expressions (cap or abstain)
#   - judgement_tasks:  the questions agents will answer
#   - agents:           computed by GitCrawl from the tasks (one per evidence domain)
#
# Pillar names, weights, bands and criteria text come from clause.md — change them there.
# Approve with:  gitcrawl plan approve <this file>
# Any edit after approval requires approving again.
"""


def dump_plan(plan: EvaluationPlan) -> str:
    body = yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False, allow_unicode=True, width=110)
    return _HEADER + "\n" + body


def write_plan(plan: EvaluationPlan, path: Path | str) -> None:
    Path(path).write_text(dump_plan(plan), encoding="utf-8")


def parse_plan(text: str, source: str = "plan") -> EvaluationPlan:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise PlanError(f"{source}: not valid YAML: {e}") from e
    if not isinstance(data, dict):
        raise PlanError(f"{source}: expected a YAML mapping at the top level")
    try:
        return EvaluationPlan.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        raise PlanError(f"{source}: invalid plan at {loc}: {first['msg']} ({e.error_count()} problem(s))") from e


def load_plan(path: Path | str) -> EvaluationPlan:
    p = Path(path)
    if not p.is_file():
        raise PlanError(f"plan file not found: {p}")
    return parse_plan(p.read_text(encoding="utf-8"), source=str(p))


def approve(plan: EvaluationPlan) -> EvaluationPlan:
    return plan.model_copy(update={"approved": True, "approved_hash": plan.content_hash()})


def load_plan_and_rubric(plan_path: Path | str | None = None, clause_path: Path | str | None = None):
    """The plan to run and the rubric to check it against.

    No plan: the bundled default plan and rubric. A plan: its clause.md from
    --clause if given, else the plan's own rubric_path (relative to the plan
    file), else the bundled default rubric."""
    from gitcrawl.rubric import load_default_rubric, load_rubric

    if plan_path is None:
        if clause_path is not None:
            raise PlanError("--clause needs --plan: generate a plan for it first with `gitcrawl plan <clause.md>`")
        return load_default_plan(), load_default_rubric()

    plan = load_plan(plan_path)
    if clause_path is not None:
        return plan, load_rubric(clause_path)
    if plan.rubric_path:
        rubric_file = Path(plan.rubric_path)
        if not rubric_file.is_absolute():
            rubric_file = Path(plan_path).parent / rubric_file
        if not rubric_file.is_file():
            raise PlanError(f"the plan's clause.md was not found at {rubric_file} — pass it with --clause")
        return plan, load_rubric(rubric_file)
    return plan, load_default_rubric()


def load_default_plan() -> EvaluationPlan:
    ref = resources.files("gitcrawl").joinpath("defaults/plan.yaml")
    if not ref.is_file():
        raise PlanError("the bundled default plan is missing — run `gitcrawl plan` to generate one")
    return parse_plan(ref.read_text(encoding="utf-8"), source="default plan")
