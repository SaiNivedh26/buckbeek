"""The planner with its model call mocked: code-owned merging, validation,
and the one retry with validation errors fed back."""

import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from test_engine import rubric_text

from gitcrawl.agents.limiter import RateLimiter
from gitcrawl.config import get_config
from gitcrawl.plan.planner import (
    PLANNER_BRIEF,
    PlannedCheck,
    PlannedCriterion,
    PlannedRule,
    PlannedTask,
    PlannerOutput,
    build_planner_prompt,
    generate_plan,
    merge_planner_output,
    render_catalog,
)
from gitcrawl.plan.validate import PlanValidationError
from gitcrawl.rubric import parse_rubric

RULE = "If the repository has no CI configuration, score is at most 2."


def good_output(collector: str = "ci.config") -> PlannerOutput:
    return PlannerOutput(
        checks=[PlannedCheck(id="ci", collector=collector, params_json="{}", why="CI triggers and steps")],
        criteria=[
            PlannedCriterion(criterion_id="ci_cd_1", status="measured", check_ids=["ci"]),
            PlannedCriterion(criterion_id="ci_cd_2", status="judgement", task_ids=["ci_steps"]),
            PlannedCriterion(criterion_id="ci_cd_3", status="not_measurable", reason="approvals are not visible"),
        ],
        rules=[PlannedRule(rule_id="ci_cd_rule_1", when="ci.has_ci == false", action="cap", cap=2)],
        judgement_tasks=[
            PlannedTask(
                id="ci_steps",
                pillar_id="ci_cd",
                criterion_ids=["ci_cd_2"],
                question="Do the pipeline steps do real work?",
                evidence_domain="ci",
                check_ids=["ci"],
            )
        ],
    )


def _agent(*outputs):
    agent = MagicMock()
    agent.arun = AsyncMock(side_effect=[MagicMock(content=o) for o in outputs])
    return agent


def test_merge_takes_names_weights_and_text_from_the_rubric():
    rubric = parse_rubric(rubric_text(RULE))
    plan, errors = merge_planner_output(rubric, good_output(), cfg=get_config(), model="m")
    assert errors == []
    pillar = plan.pillars[0]
    assert pillar.name == "CI/CD" and pillar.weight == 1.0
    assert [c.text for c in pillar.criteria] == rubric.pillars[0].criteria
    assert pillar.rules[0].source_text == RULE
    assert [a.id for a in plan.agents] == ["ci_agent"]
    assert not plan.approved


def test_merge_reports_unplanned_criteria_bad_json_and_unknown_ids():
    rubric = parse_rubric(rubric_text(RULE))
    out = good_output()
    out.criteria.pop(2)
    out.criteria.append(PlannedCriterion(criterion_id="ci_cd_9", status="measured", check_ids=["ci"]))
    out.checks[0].params_json = "[1, 2]"
    _, errors = merge_planner_output(rubric, out, cfg=get_config(), model="m")
    joined = "\n".join(errors)
    assert "criterion 'ci_cd_3'" in joined and "was not planned" in joined
    assert "unknown criterion id 'ci_cd_9'" in joined
    assert "params_json must be a JSON object" in joined


def test_question_with_tool_call_syntax_is_rejected():
    rubric = parse_rubric(rubric_text(RULE))
    out = good_output()
    out.judgement_tasks[0].question = "Use read_file(path) on the workflow and judge it."
    _, errors = merge_planner_output(rubric, out, cfg=get_config(), model="m")
    assert any("tool call syntax" in e for e in errors)


async def test_generate_plan_retries_once_with_the_validation_errors():
    rubric = parse_rubric(rubric_text(RULE))
    agent = _agent(good_output(collector="ci.nonexistent"), good_output())
    with (
        patch("gitcrawl.plan.planner.build_planner_agent", return_value=agent),
        patch("gitcrawl.plan.planner.limiter_for", return_value=RateLimiter(None)),
    ):
        plan = await generate_plan(rubric, cfg=get_config(), rubric_path="clause.md")
    assert plan.rubric_path == "clause.md"
    second_prompt = agent.arun.call_args_list[1].args[0]
    assert "PROBLEMS" in second_prompt and "unknown collector 'ci.nonexistent'" in second_prompt


async def test_generate_plan_gives_up_with_errors_instead_of_writing_a_broken_plan():
    rubric = parse_rubric(rubric_text(RULE))
    bad = good_output(collector="ci.nonexistent")
    with (
        patch("gitcrawl.plan.planner.build_planner_agent", return_value=_agent(bad, bad)),
        patch("gitcrawl.plan.planner.limiter_for", return_value=RateLimiter(None)),
    ):
        with pytest.raises(PlanValidationError, match="unknown collector"):
            await generate_plan(rubric, cfg=get_config())


def test_prompt_lists_ids_catalog_and_has_no_tool_call_syntax():
    rubric = parse_rubric(rubric_text(RULE))
    prompt = build_planner_prompt(rubric)
    assert "ci_cd_1: CI runs tests on every pull request." in prompt
    assert "ci_cd_rule_1: " + RULE in prompt
    for name in ("repo.inventory", "ci.config", "tests.mapping", "code.imports", "github.workflow_runs"):
        assert f"- {name}" in render_catalog()
    call_syntax = re.compile(r"(list_directory|read_file|search_repo|get_issue_thread)\s*\(")
    assert call_syntax.search(PLANNER_BRIEF) is None and call_syntax.search(prompt) is None
