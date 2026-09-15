from pathlib import Path

import pytest

from gitcrawl.config import get_config
from gitcrawl.plan.agents import compute_agents
from gitcrawl.plan.io import PlanError, approve, dump_plan, load_plan, parse_plan, write_plan
from gitcrawl.plan.models import CheckRef, CriterionPlan, EvaluationPlan, JudgementTask, PillarPlan, Rule
from gitcrawl.plan.validate import validate_plan
from gitcrawl.rubric import parse_rubric

RUBRIC_TEXT = """\
# Tiny rubric
Version: 0.1

## Pillar: Security
Weight: 60%

### Criteria
- A security policy exists.
- Dependencies are updated automatically.
- Vulnerability alerts are resolved quickly.

### Bands
- 0-4: Nothing in place.
- 5-10: Some policy.

### Hard rules
- If there is no security policy, score is at most 4.

## Pillar: Docs
Weight: 40%

### Criteria
- The README explains installation and usage.

### Bands
- 0-5: Poor.
- 6-10: Good.
"""


def make_plan() -> tuple[EvaluationPlan, object]:
    rubric = parse_rubric(RUBRIC_TEXT)
    sec, docs = rubric.pillars
    tasks = [
        JudgementTask(
            id="readme_usage",
            pillar_id="docs",
            criterion_ids=["docs_1"],
            question="Does the README explain installation and usage?",
            evidence_domain="docs_community",
            check_ids=["inventory"],
        )
    ]
    plan = EvaluationPlan(
        rubric_title=rubric.title,
        rubric_version=rubric.version,
        rubric_hash=rubric.content_hash,
        catalog_version="test",
        planner_model="test",
        created_at="2026-09-15T00:00:00Z",
        checks=[
            CheckRef(
                id="security_policy", collector="file.exists", params={"globs": ["SECURITY.md"]}, why="policy"
            ),
            CheckRef(id="ci", collector="ci.config", why="dependabot"),
            CheckRef(id="inventory", collector="repo.inventory", why="README presence"),
        ],
        pillars=[
            PillarPlan(
                id=sec.id,
                name=sec.name,
                weight=sec.weight,
                bands=sec.bands,
                criteria=[
                    CriterionPlan(
                        id="security_1", text=sec.criteria[0], status="measured", check_ids=["security_policy"]
                    ),
                    CriterionPlan(id="security_2", text=sec.criteria[1], status="measured", check_ids=["ci"]),
                    CriterionPlan(
                        id="security_3",
                        text=sec.criteria[2],
                        status="not_measurable",
                        reason="alert data needs admin access",
                    ),
                ],
                rules=[
                    Rule(
                        id="security_rule_1",
                        source_text=sec.hard_rules[0],
                        when="security_policy.found == false",
                        action="cap",
                        cap=4,
                    )
                ],
            ),
            PillarPlan(
                id=docs.id,
                name=docs.name,
                weight=docs.weight,
                bands=docs.bands,
                criteria=[
                    CriterionPlan(
                        id="docs_1", text=docs.criteria[0], status="judgement", task_ids=["readme_usage"]
                    )
                ],
            ),
        ],
        judgement_tasks=tasks,
        agents=compute_agents(tasks, get_config()),
    )
    return plan, rubric


def test_valid_plan_has_no_errors():
    plan, rubric = make_plan()
    assert validate_plan(plan, rubric) == []


def test_agents_are_grouped_by_evidence_domain_with_configured_budgets():
    plan, _ = make_plan()
    extra = JudgementTask(
        id="changelog", pillar_id="docs", criterion_ids=["docs_1"], question="q", evidence_domain="docs_community"
    )
    code = JudgementTask(
        id="layering",
        pillar_id="security",
        criterion_ids=["security_1"],
        question="q",
        evidence_domain="source_code",
    )
    agents = compute_agents([*plan.judgement_tasks, extra, code], get_config())
    assert [(a.id, a.task_ids) for a in agents] == [
        ("source_code_agent", ["layering"]),
        ("docs_community_agent", ["readme_usage", "changelog"]),
    ]
    assert agents[0].budget == get_config().agents.budgets["source_code"]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda p: p.checks.append(CheckRef(id="ghost", collector="nope.nope")), "unknown collector"),
        (lambda p: p.checks[0].params.update(globs=[]), "invalid param globs"),
        (lambda p: setattr(p.pillars[0], "weight", 0.9), "name/weight differ"),
        (lambda p: setattr(p.pillars[0].criteria[0], "text", "reworded"), "criteria differ"),
        (lambda p: setattr(p.pillars[0].criteria[2], "reason", ""), "needs a reason"),
        (lambda p: setattr(p.pillars[0].criteria[0], "check_ids", []), "needs at least one check"),
        (
            lambda p: setattr(p.pillars[0].rules[0], "when", "security_policy.exists == false"),
            "has no field 'exists'",
        ),
        (lambda p: setattr(p.pillars[0].rules[0], "when", "__import__('os')"), "not allowed"),
        (lambda p: p.pillars[0].rules.clear(), "must be mapped to exactly one rule"),
        (lambda p: setattr(p.pillars[0].rules[0], "cap", None), "needs a cap value"),
        (lambda p: setattr(p.judgement_tasks[0], "criterion_ids", ["security_1"]), "is not in pillar"),
        (lambda p: p.agents.clear(), "assigned to exactly one agent"),
        (lambda p: setattr(p, "rubric_hash", "other"), "rubric hash mismatch"),
        (lambda p: p.checks.append(CheckRef(id="unused", collector="repo.inventory")), "is not used"),
    ],
)
def test_validation_catches_bad_plans(mutate, expected):
    plan, rubric = make_plan()
    mutate(plan)
    errors = validate_plan(plan, rubric)
    assert any(expected in e for e in errors), errors


def test_yaml_round_trip_and_approval_is_invalidated_by_edits(tmp_path: Path):
    plan, _ = make_plan()
    approved = approve(plan)
    path = tmp_path / "plan.yaml"
    write_plan(approved, path)
    loaded = load_plan(path)
    assert loaded == approved
    assert loaded.is_approved()
    assert dump_plan(loaded).startswith("# GitCrawl Evaluation Plan")

    edited = path.read_text().replace("SECURITY.md", "SECURITY.txt")
    assert not parse_plan(edited).is_approved()


def test_unapproved_plan_is_not_approved():
    plan, _ = make_plan()
    assert not plan.is_approved()


def test_malformed_plan_file_gives_readable_error(tmp_path: Path):
    bad = tmp_path / "plan.yaml"
    bad.write_text("pillars: 3\n")
    with pytest.raises(PlanError, match="invalid plan"):
        load_plan(bad)
    with pytest.raises(PlanError, match="not found"):
        load_plan(tmp_path / "missing.yaml")
