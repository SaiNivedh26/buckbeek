"""Load and verify the rubric/plan pinned into a Cloud Run revision."""

from __future__ import annotations

from dataclasses import dataclass

from gitcrawl.hosted.rubric import agent_version_prefix, eval_hash, parse_agent_id
from gitcrawl.plan.io import parse_plan
from gitcrawl.plan.validate import PlanValidationError, validate_plan
from gitcrawl.rubric import parse_rubric


@dataclass(frozen=True)
class PinnedArtifacts:
    rubric: object
    plan: object


def load_pinned(store, *, agent_id: str, expected_eval_hash: str, expected_plan_hash: str) -> PinnedArtifacts:
    prefix = agent_version_prefix(agent_id, expected_eval_hash)
    eval_text = store.read_text(f"{prefix}/eval.md")
    plan_text = store.read_text(f"{prefix}/plan.yaml")
    if eval_text is None or plan_text is None:
        raise RuntimeError("pinned eval.md or plan.yaml is missing from Cloud Storage")
    if eval_hash(eval_text) != expected_eval_hash:
        raise RuntimeError("pinned eval.md hash does not match GITCRAWL_EVAL_HASH")
    if parse_agent_id(eval_text) != agent_id:
        raise RuntimeError("pinned eval.md Agent-ID does not match GITCRAWL_AGENT_ID")
    rubric = parse_rubric(eval_text)
    plan = parse_plan(plan_text, source=f"gs://.../{prefix}/plan.yaml")
    if plan.content_hash() != expected_plan_hash or not plan.is_approved():
        raise RuntimeError("pinned plan hash or approval does not match GITCRAWL_PLAN_HASH")
    errors = validate_plan(plan, rubric)
    if errors:
        raise PlanValidationError(errors)
    return PinnedArtifacts(rubric=rubric, plan=plan)
