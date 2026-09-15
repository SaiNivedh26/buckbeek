"""The bundled default plan must always be valid against the bundled default
rubric and the current collector catalog, and approved — `gitcrawl evaluate`
with no --plan depends on it. Regenerate it if a collector's fields change."""

from gitcrawl.plan.io import load_default_plan, load_plan_and_rubric
from gitcrawl.plan.validate import validate_plan
from gitcrawl.rubric import load_default_rubric


def test_default_plan_is_valid_and_approved():
    plan = load_default_plan()
    rubric = load_default_rubric()
    assert validate_plan(plan, rubric) == []
    assert plan.is_approved()


def test_default_plan_covers_every_default_criterion_and_hard_rule():
    plan, rubric = load_plan_and_rubric()
    for spec, pillar in zip(rubric.pillars, plan.pillars, strict=True):
        assert [c.text for c in pillar.criteria] == spec.criteria
        assert sorted(r.source_text for r in pillar.rules) == sorted(spec.hard_rules)
    not_measurable = [c for p in plan.pillars for c in p.criteria if c.status == "not_measurable"]
    assert [c.id for c in not_measurable] == ["community_6"]  # adoption: no data source
