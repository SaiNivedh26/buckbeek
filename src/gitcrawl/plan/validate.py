"""Plan validation. Runs when a plan is generated, when it is approved, and
again before every evaluation — so a hand-edited plan, or a plan written
against an older collector catalog, is caught before anything runs.

Returns every problem found, not just the first.
"""

from __future__ import annotations

import re

from gitcrawl.collectors import REGISTRY, validate_check
from gitcrawl.plan import rules
from gitcrawl.plan.agents import KNOWN_TOOLS
from gitcrawl.plan.models import EvaluationPlan
from gitcrawl.rubric.models import Rubric

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CALL_SYNTAX_RE = re.compile(r"\b(" + "|".join(sorted(KNOWN_TOOLS)) + r")\s*\(")


class PlanValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("plan is invalid:\n" + "\n".join(f"  - {e}" for e in errors))


def validate_plan(plan: EvaluationPlan, rubric: Rubric) -> list[str]:
    errors: list[str] = []

    if plan.rubric_hash != rubric.content_hash:
        errors.append(
            "plan was generated from a different clause.md (rubric hash mismatch) — re-run `gitcrawl plan`"
        )

    # --- checks ------------------------------------------------------------
    check_ids = [c.id for c in plan.checks]
    for dup in sorted({i for i in check_ids if check_ids.count(i) > 1}):
        errors.append(f"duplicate check id {dup!r}")
    check_fields: dict[str, set[str]] = {}
    for c in plan.checks:
        if not _ID_RE.match(c.id):
            errors.append(f"check id {c.id!r} must be lowercase letters, digits and underscores")
        problems = validate_check(c.collector, c.params)
        errors.extend(f"check {c.id!r}: {p}" for p in problems)
        if c.collector in REGISTRY:
            check_fields[c.id] = set(REGISTRY[c.collector].output_fields())

    # --- pillars: code-owned fields must match the rubric exactly ----------
    plan_ids = [p.id for p in plan.pillars]
    rubric_ids = [p.id for p in rubric.pillars]
    if plan_ids != rubric_ids:
        errors.append(f"plan pillars {plan_ids} do not match clause.md pillars {rubric_ids}")

    task_ids = {t.id for t in plan.judgement_tasks}
    used_checks: set[str] = set()

    for pillar in plan.pillars:
        where = f"pillar {pillar.id!r}"
        try:
            spec = rubric.pillar(pillar.id)
        except KeyError:
            continue
        if pillar.name != spec.name or abs(pillar.weight - spec.weight) > 1e-9:
            errors.append(f"{where}: name/weight differ from clause.md (edit clause.md, not the plan)")
        if [b.model_dump() for b in pillar.bands] != [b.model_dump() for b in spec.bands]:
            errors.append(f"{where}: bands differ from clause.md (edit clause.md, not the plan)")
        if [c.text for c in pillar.criteria] != spec.criteria:
            errors.append(f"{where}: criteria differ from clause.md (edit clause.md, not the plan)")

        for c in pillar.criteria:
            cw = f"{where} criterion {c.id!r}"
            for cid in c.check_ids:
                if cid not in check_fields and cid not in check_ids:
                    errors.append(f"{cw}: unknown check {cid!r}")
                used_checks.add(cid)
            for tid in c.task_ids:
                if tid not in task_ids:
                    errors.append(f"{cw}: unknown judgement task {tid!r}")
            if c.status == "measured" and not c.check_ids:
                errors.append(f"{cw}: status 'measured' needs at least one check")
            if c.status == "judgement" and not c.task_ids:
                errors.append(f"{cw}: status 'judgement' needs a judgement task")
            if c.status == "not_measurable":
                if not c.reason.strip():
                    errors.append(f"{cw}: status 'not_measurable' needs a reason")
                if c.check_ids or c.task_ids:
                    errors.append(f"{cw}: a not_measurable criterion cannot have checks or tasks")

        mapped = [r.source_text for r in pillar.rules]
        for hard_rule in spec.hard_rules:
            if mapped.count(hard_rule) != 1:
                errors.append(f"{where}: hard rule {hard_rule!r} must be mapped to exactly one rule")
        for r in pillar.rules:
            rw = f"{where} rule {r.id!r}"
            if r.source_text not in spec.hard_rules:
                errors.append(f"{rw}: source_text is not a hard rule in clause.md")
            if r.action == "cap" and r.cap is None:
                errors.append(f"{rw}: action 'cap' needs a cap value")
            if r.action == "abstain" and r.cap is not None:
                errors.append(f"{rw}: action 'abstain' must not set a cap")
            errors.extend(f"{rw}: {e}" for e in rules.validate(r.when, check_fields))
            used_checks.update(ref for ref, _ in _safe_refs(r.when))

    # --- judgement tasks --------------------------------------------------
    all_tids = [t.id for t in plan.judgement_tasks]
    for dup in sorted({i for i in all_tids if all_tids.count(i) > 1}):
        errors.append(f"duplicate judgement task id {dup!r}")
    for t in plan.judgement_tasks:
        tw = f"judgement task {t.id!r}"
        if not _ID_RE.match(t.id):
            errors.append(f"{tw}: id must be lowercase letters, digits and underscores")
        try:
            pillar = plan.pillar(t.pillar_id)
        except KeyError:
            errors.append(f"{tw}: unknown pillar {t.pillar_id!r}")
            continue
        pillar_criteria = {c.id for c in pillar.criteria}
        for cid in t.criterion_ids:
            if cid not in pillar_criteria:
                errors.append(f"{tw}: criterion {cid!r} is not in pillar {t.pillar_id!r}")
        for chk in t.check_ids:
            if chk not in check_ids:
                errors.append(f"{tw}: unknown check {chk!r}")
            used_checks.add(chk)
        if not t.question.strip():
            errors.append(f"{tw}: question is empty")
        elif _CALL_SYNTAX_RE.search(t.question):
            # A weaker model copies call syntax verbatim as the tool name ("Function ... not found").
            errors.append(f"{tw}: question must not contain tool call syntax like name(...)")

    for unused in sorted(set(check_ids) - used_checks):
        errors.append(f"check {unused!r} is not used by any criterion, rule or judgement task")

    # --- agents (computed by code; a hand edit must stay consistent) -------
    assigned = [tid for a in plan.agents for tid in a.task_ids]
    for tid in sorted(task_ids):
        if assigned.count(tid) != 1:
            errors.append(f"judgement task {tid!r} must be assigned to exactly one agent")
    for a in plan.agents:
        for tid in a.task_ids:
            if tid in task_ids and plan.task(tid).evidence_domain != a.evidence_domain:
                errors.append(f"agent {a.id!r}: task {tid!r} belongs to a different evidence domain")
        for tool in a.tools:
            if tool not in KNOWN_TOOLS:
                errors.append(f"agent {a.id!r}: unknown tool {tool!r}")
        if a.budget < 1:
            errors.append(f"agent {a.id!r}: budget must be at least 1")

    return errors


def _safe_refs(expr: str) -> list[tuple[str, str]]:
    try:
        return rules.references(expr)
    except rules.RuleError:
        return []


def ensure_valid(plan: EvaluationPlan, rubric: Rubric) -> None:
    errors = validate_plan(plan, rubric)
    if errors:
        raise PlanValidationError(errors)
