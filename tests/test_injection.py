"""Repository content that addresses the evaluator must reach models only as
wrapped, untrusted data — including facts rendered into prompts, since file
names and matched lines are repository-controlled."""

from pathlib import Path

from gitcrawl.agents.judge import JUDGE_BRIEF, build_judge_prompt
from gitcrawl.agents.pillar_scorer import SCORER_BRIEF, build_scorer_prompt
from gitcrawl.collectors import CheckRequest, CollectorContext, RepoFiles, run_check
from gitcrawl.config import get_config
from gitcrawl.plan.agents import compute_agents
from gitcrawl.plan.models import CheckRef, CriterionPlan, EvaluationPlan, JudgementTask, PillarPlan
from gitcrawl.rubric.models import Band
from gitcrawl.source import local_handle

FIXTURE = Path(__file__).parent / "fixtures" / "injection"


async def test_injected_text_in_facts_stays_inside_the_untrusted_wrapper():
    ctx = CollectorContext(handle=local_handle(FIXTURE), cfg=get_config(), files=RepoFiles(FIXTURE))
    fact = await run_check(
        CheckRequest("readme_claims", "file.contains", {"globs": ["README.md"], "pattern": "(?i)override|score"}),
        ctx,
    )
    assert fact.ok and fact.data["found"], "fixture README should contain the injection text"
    injected = fact.data["matches"][0].split(": ", 1)[1]

    task = JudgementTask(
        id="readme_quality",
        pillar_id="docs",
        criterion_ids=["docs_1"],
        question="Is the README useful?",
        evidence_domain="docs_community",
        check_ids=["readme_claims"],
    )
    plan = EvaluationPlan(
        rubric_title="t",
        rubric_version="1",
        rubric_hash="h",
        catalog_version="c",
        planner_model="m",
        created_at="now",
        checks=[CheckRef(id="readme_claims", collector="file.contains", params=fact.params)],
        pillars=[
            PillarPlan(
                id="docs",
                name="Docs",
                weight=1.0,
                bands=[Band(low=0, high=10, text="any")],
                criteria=[CriterionPlan(id="docs_1", text="README is useful", status="measured",
                                        check_ids=["readme_claims"])],
            )
        ],
        judgement_tasks=[task],
        agents=compute_agents([task], get_config()),
    )  # fmt: skip
    facts = {"readme_claims": fact}

    for prompt in (
        build_judge_prompt(plan.agents[0], plan, facts),
        build_scorer_prompt(plan.pillars[0], plan, facts, {}, None),
    ):
        start = prompt.index("<untrusted-repo-content")
        end = prompt.index("</untrusted-repo-content>")
        position = prompt.index(injected[:40])
        assert start < position < end

    assert "never instructions" in JUDGE_BRIEF
    assert "never an instruction" in SCORER_BRIEF
