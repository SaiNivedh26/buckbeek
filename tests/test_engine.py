"""The plan executor, end to end over real fixtures and real collectors, with
the two model-facing builders mocked (no API calls)."""

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from gitcrawl.agents.judge import JUDGE_BRIEF, JudgementOutput, TaskAnswerOutput, build_judge_prompt
from gitcrawl.agents.limiter import RateLimiter
from gitcrawl.agents.pillar_scorer import SCORER_BRIEF, ScoreOutput
from gitcrawl.config import get_config
from gitcrawl.engine import PreflightError, evaluate, evaluate_handle
from gitcrawl.plan.agents import compute_agents
from gitcrawl.plan.io import approve
from gitcrawl.plan.models import CheckRef, CriterionPlan, EvaluationPlan, JudgementTask, PillarPlan, Rule
from gitcrawl.rubric import parse_rubric
from gitcrawl.source import local_handle
from gitcrawl.storage import db

FIXTURES = Path(__file__).parent / "fixtures"

CAP_RULE = "If the repository has no CI configuration, score is at most 2."
ABSTAIN_RULE = "If the repository has no CI configuration, the pillar is not assessed."


def rubric_text(hard_rule: str) -> str:
    return f"""\
# CI rubric
Version: 1

## Pillar: CI/CD
Weight: 100%

### Criteria
- CI runs tests on every pull request.
- Pipeline steps do real work rather than placeholders.
- Deployments are approved by a human.

### Bands
- 0-3: Weak.
- 4-7: Decent.
- 8-10: Strong.

### Hard rules
- {hard_rule}
"""


def make_plan(hard_rule: str = CAP_RULE, *, approved: bool = True):
    rubric = parse_rubric(rubric_text(hard_rule))
    spec = rubric.pillars[0]
    task = JudgementTask(
        id="ci_steps",
        pillar_id=spec.id,
        criterion_ids=["ci_cd_2"],
        question="Do the pipeline steps do real work rather than placeholders?",
        evidence_domain="ci",
        check_ids=["ci"],
    )
    abstain = hard_rule == ABSTAIN_RULE
    plan = EvaluationPlan(
        rubric_title=rubric.title,
        rubric_version=rubric.version,
        rubric_hash=rubric.content_hash,
        catalog_version="test",
        planner_model="test",
        created_at="2026-09-15T00:00:00Z",
        checks=[CheckRef(id="ci", collector="ci.config", why="CI triggers and steps")],
        pillars=[
            PillarPlan(
                id=spec.id,
                name=spec.name,
                weight=spec.weight,
                bands=spec.bands,
                criteria=[
                    CriterionPlan(id="ci_cd_1", text=spec.criteria[0], status="measured", check_ids=["ci"]),
                    CriterionPlan(id="ci_cd_2", text=spec.criteria[1], status="judgement", task_ids=["ci_steps"]),
                    CriterionPlan(
                        id="ci_cd_3",
                        text=spec.criteria[2],
                        status="not_measurable",
                        reason="approvals are not visible in files or public API data",
                    ),
                ],
                rules=[
                    Rule(
                        id="ci_cd_rule_1",
                        source_text=hard_rule,
                        when="ci.has_ci == false",
                        action="abstain" if abstain else "cap",
                        cap=None if abstain else 2,
                    )
                ],
            )
        ],
        judgement_tasks=[task],
        agents=compute_agents([task], get_config()),
    )
    return (approve(plan) if approved else plan), rubric


class _Run:
    def __init__(self, content):
        self.content = content


def _judge_output(citations=(".github/workflows/ci.yml", "src/never_read.py")):
    return JudgementOutput(
        answers=[
            TaskAnswerOutput(
                task_id="ci_steps",
                answer="Steps run ruff, pytest and pip-audit.",
                confidence="high",
                citations=list(citations),
            )
        ]
    )


def _mock_agent(content=None, side_effect=None):
    agent = MagicMock()
    agent.arun = AsyncMock(return_value=_Run(content), side_effect=side_effect)
    return agent


async def _run(fixture: str, plan, *, conn=None, judge=None, scorer=None):
    judge = judge or _mock_agent(_judge_output())
    scorer = scorer or _mock_agent(ScoreOutput(score=8, reasoning="PR-triggered tests, lint and audit."))
    with (
        patch("gitcrawl.engine.build_judge_agent", return_value=judge) as build_judge,
        patch("gitcrawl.engine.build_pillar_scorer", return_value=scorer) as build_scorer,
    ):
        report = await evaluate_handle(
            local_handle(FIXTURES / fixture), plan, cfg=get_config(), conn=conn, limiter=RateLimiter(None)
        )
    return report, build_judge, build_scorer


async def test_end_to_end_scores_with_facts_judgements_and_exclusions():
    plan, _ = make_plan()
    report, build_judge, build_scorer = await _run("ci_rich", plan)

    [pillar] = report.pillars
    assert pillar.score == 8 and not pillar.abstained
    assert report.total_score == 8.0 and report.rubric_coverage == 1.0
    assert pillar.caps_applied == []  # ci_rich has CI, the rule did not fire
    assert pillar.not_measured and "approvals" in pillar.not_measured[0]
    assert report.facts["ci"].data["tests_run_on_pull_request"] is True

    [answer] = report.judgements
    assert answer.unverified_citations == ["src/never_read.py"]  # never read, not in the facts it was shown
    assert report.scope.unverified_citations == 1
    build_judge.assert_called_once()
    build_scorer.assert_called_once()


async def test_cap_rule_is_enforced_by_code_even_when_scorer_goes_higher():
    plan, _ = make_plan()
    report, _, _ = await _run("no_tests", plan)
    [pillar] = report.pillars
    assert pillar.scorer_score == 8
    assert pillar.score == 2
    assert pillar.caps_applied and pillar.caps_applied[0].startswith("lowered 8 → 2")


async def test_abstain_rule_skips_the_agent_and_scorer_entirely():
    plan, _ = make_plan(ABSTAIN_RULE)
    report, build_judge, build_scorer = await _run("no_tests", plan)
    [pillar] = report.pillars
    assert pillar.abstained and ABSTAIN_RULE in pillar.abstain_reason
    assert report.total_score is None
    build_judge.assert_not_called()
    build_scorer.assert_not_called()


async def test_second_run_is_served_from_cache():
    plan, _ = make_plan()
    conn = db.connect(":memory:")
    first, _, _ = await _run("ci_rich", plan, conn=conn)
    second, build_judge, build_scorer = await _run("ci_rich", plan, conn=conn)
    build_judge.assert_not_called()
    build_scorer.assert_not_called()
    assert second.pillars[0].cached and second.pillars[0].score == first.pillars[0].score
    assert second.scope.facts_cached == 1 and second.scope.agents_cached == 1


async def test_failures_abstain_visibly_and_are_not_cached(caplog):
    plan, _ = make_plan()
    conn = db.connect(":memory:")
    broken_judge = _mock_agent(side_effect=RuntimeError("provider down"))
    broken_scorer = _mock_agent(side_effect=RuntimeError("provider down"))
    report, _, _ = await _run("ci_rich", plan, conn=conn, judge=broken_judge, scorer=broken_scorer)
    [pillar] = report.pillars
    assert pillar.abstained and "scorer failed" in pillar.abstain_reason
    assert report.scope.agents_failed == ["ci_agent"]
    assert "judgement agent ci_agent failed" in caplog.text

    retried, build_judge, build_scorer = await _run("ci_rich", plan, conn=conn)
    build_judge.assert_called_once()
    build_scorer.assert_called_once()
    assert retried.pillars[0].score == 8


async def test_pillar_with_no_usable_evidence_abstains_without_a_scorer_call():
    plan, _ = make_plan()
    plan.checks[0].collector = "file.exists"  # break the check: missing required params
    plan = approve(plan)
    report, _, build_scorer = await _run("ci_rich", plan, judge=_mock_agent(JudgementOutput(answers=[])))
    [pillar] = report.pillars
    assert pillar.abstained and "no usable evidence" in pillar.abstain_reason
    build_scorer.assert_not_called()


async def test_preflight_refuses_unapproved_and_edited_plans_before_cloning():
    plan, rubric = make_plan(approved=False)
    with patch("gitcrawl.source.resolve") as resolve:
        with pytest.raises(PreflightError, match="not approved"):
            await evaluate("owner/repo", plan, rubric)
        approved, _ = make_plan()
        approved.pillars[0].rules[0].cap = 5
        with pytest.raises(PreflightError, match="edited after it was approved"):
            await evaluate("owner/repo", approved, rubric)
        resolve.assert_not_called()


def test_briefs_and_prompts_have_no_tool_call_syntax():
    call_syntax = re.compile(
        r"(list_directory|read_file|search_repo|get_issue_thread|get_pull_request_thread"
        r"|get_release_notes)\s*\("
    )
    plan, _ = make_plan()
    prompt = build_judge_prompt(plan.agents[0], plan, {})
    for text in (JUDGE_BRIEF, SCORER_BRIEF, prompt):
        assert call_syntax.search(text) is None


def test_rate_limiter_spaces_requests():
    now = {"t": 100.0}
    slept: list[float] = []

    def sleep(s):
        slept.append(s)
        now["t"] += s

    limiter = RateLimiter(60, clock=lambda: now["t"], sleep=sleep)
    for _ in range(3):
        limiter.acquire_sync()
    assert slept == [1.0, 1.0]
    assert limiter.acquired == 3
