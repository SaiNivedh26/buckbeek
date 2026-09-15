"""Builds src/gitcrawl/defaults/plan.yaml for the bundled default rubric.

Written by hand (not by the planner model) so the shipped default is
deterministic and reviewed; it still goes through the same code-owned merge
and validation as a planner-generated plan.
"""

import sys

from gitcrawl.config import get_config
from gitcrawl.plan.io import approve, write_plan
from gitcrawl.plan.planner import PlannedCheck, PlannedCriterion, PlannedRule, PlannedTask, PlannerOutput, merge_planner_output
from gitcrawl.rubric import load_default_rubric

C = PlannedCheck
M = lambda cid, *checks: PlannedCriterion(criterion_id=cid, status="measured", check_ids=list(checks))  # noqa: E731
J = lambda cid, *tasks: PlannedCriterion(criterion_id=cid, status="judgement", task_ids=list(tasks))  # noqa: E731

output = PlannerOutput(
    checks=[
        C(id="inventory", collector="repo.inventory", why="README/LICENSE/CONTRIBUTING/templates presence; file counts"),
        C(id="code_structure", collector="code.structure", why="file sizes, god-file candidates, docs density"),
        C(id="code_imports", collector="code.imports", why="coupling hot spots and import cycles"),
        C(id="tests_inventory", collector="tests.inventory", why="whether tests exist, frameworks, unit/integration/e2e split"),
        C(id="tests_mapping", collector="tests.mapping", why="which source modules tests reach"),
        C(id="tests_coverage", collector="tests.coverage", why="coverage reports, thresholds, badges"),
        C(id="ci_config", collector="ci.config", why="CI systems, triggers, classified steps, gates"),
        C(id="workflow_runs", collector="github.workflow_runs", why="CI pass rates and failure streak"),
        C(id="github_issues", collector="github.issues", why="close rate, staleness, maintainer response, labels"),
        C(id="github_prs", collector="github.pull_requests", why="review latency and review-before-merge"),
        C(id="github_repo", collector="github.repo", why="stars, forks, watchers, recent activity"),
        C(id="contributors", collector="github.contributors", why="contributor count and commit concentration"),
        C(id="releases", collector="github.releases", why="release cadence and notes"),
    ],
    criteria=[
        # Code Health
        J("code_health_1", "architecture_coupling"),
        J("code_health_2", "architecture_coupling"),
        M("code_health_3", "code_structure"),
        J("code_health_4", "duplication"),
        J("code_health_5", "readability_docs"),
        # Test Coverage
        M("test_coverage_1", "tests_inventory"),
        M("test_coverage_2", "tests_mapping"),
        M("test_coverage_3", "tests_coverage"),
        M("test_coverage_4", "tests_inventory"),
        J("test_coverage_5", "test_quality"),
        M("test_coverage_6", "ci_config"),
        # CI/CD
        M("ci_cd_1", "ci_config"),
        M("ci_cd_2", "ci_config"),
        M("ci_cd_3", "ci_config"),
        M("ci_cd_4", "ci_config", "tests_coverage"),
        M("ci_cd_5", "workflow_runs"),
        M("ci_cd_6", "ci_config"),
        # Issue Management
        M("issue_management_1", "github_issues"),
        M("issue_management_2", "github_issues", "inventory"),
        M("issue_management_3", "github_issues", "github_prs"),
        J("issue_management_4", "contributing_workflow"),
        J("issue_management_5", "discussion_quality"),
        # Community
        M("community_1", "github_repo"),
        M("community_2", "contributors"),
        J("community_3", "release_notes"),
        M("community_4", "github_repo"),
        M("community_5", "inventory"),
        PlannedCriterion(
            criterion_id="community_6",
            status="not_measurable",
            reason="dependents, tutorials, talks and blog mentions are not available from repository files or the GitHub API data GitCrawl collects",
        ),
    ],
    rules=[
        PlannedRule(rule_id="test_coverage_rule_1", when="tests_inventory.test_file_count == 0", action="cap", cap=2),
        PlannedRule(rule_id="ci_cd_rule_1", when="not ci_config.has_ci", action="cap", cap=2),
        PlannedRule(
            rule_id="ci_cd_rule_2",
            when="workflow_runs.completed_runs > 0 and workflow_runs.success_rate == 0",
            action="cap",
            cap=2,
        ),
        PlannedRule(
            rule_id="community_rule_1", when="not inventory.has_readme and not inventory.has_license", action="cap", cap=3
        ),
        PlannedRule(rule_id="community_rule_2", when="contributors.contributor_count <= 1", action="cap", cap=5),
    ],
    judgement_tasks=[
        PlannedTask(
            id="architecture_coupling",
            pillar_id="code_health",
            criterion_ids=["code_health_1", "code_health_2"],
            question=(
                "Does the codebase follow a recognizable architecture (layered, feature-based or domain-based), and "
                "do modules keep a clear separation of concerns with low coupling? Read a few representative files "
                "from different top-level modules, including the most-imported ones and any import cycles, and "
                "check whether the structure the layout suggests actually holds in the imports."
            ),
            evidence_domain="source_code",
            check_ids=["code_structure", "code_imports"],
        ),
        PlannedTask(
            id="duplication",
            pillar_id="code_health",
            criterion_ids=["code_health_4"],
            question=(
                "Is there noticeable duplicated logic across the files you read (copy-pasted functions, parallel "
                "implementations of the same behaviour)? Use search to confirm any suspected duplication."
            ),
            evidence_domain="source_code",
            check_ids=["code_structure"],
        ),
        PlannedTask(
            id="readability_docs",
            pillar_id="code_health",
            criterion_ids=["code_health_5"],
            question=(
                "Is the code you read readable (clear naming, reasonable function size, consistent style) and "
                "documented where it matters (docstrings or comments on non-obvious code, architecture notes)?"
            ),
            evidence_domain="source_code",
            check_ids=["code_structure"],
        ),
        PlannedTask(
            id="test_quality",
            pillar_id="test_coverage",
            criterion_ids=["test_coverage_5"],
            question=(
                "Are the tests meaningful and well organized — do they assert real behaviour of core logic, cover "
                "edge cases and failure paths — or are they trivial smoke tests? Read two or three test files that "
                "exercise core modules."
            ),
            evidence_domain="tests",
            check_ids=["tests_inventory", "tests_mapping"],
        ),
        PlannedTask(
            id="contributing_workflow",
            pillar_id="issue_management",
            criterion_ids=["issue_management_4"],
            question=(
                "Do the contribution guidelines and issue or pull request templates clearly describe how to report "
                "issues and submit pull requests? If no such files exist, say so."
            ),
            evidence_domain="docs_community",
            check_ids=["inventory"],
        ),
        PlannedTask(
            id="discussion_quality",
            pillar_id="issue_management",
            criterion_ids=["issue_management_5"],
            question=(
                "Is discussion on issues and pull requests constructive and helpful — do maintainers engage with "
                "reporters, ask clarifying questions and explain decisions? Read two or three of the sample issue "
                "and pull request threads."
            ),
            evidence_domain="issues_prs",
            check_ids=["github_issues", "github_prs"],
        ),
        PlannedTask(
            id="release_notes",
            pillar_id="community",
            criterion_ids=["community_3"],
            question=(
                "Are releases regular, and do their notes or the CHANGELOG meaningfully describe what changed? "
                "Read the latest release notes or the top of the CHANGELOG."
            ),
            evidence_domain="docs_community",
            check_ids=["releases", "inventory"],
        ),
    ],
)

rubric = load_default_rubric()
plan, errors = merge_planner_output(rubric, output, cfg=get_config(), model="hand-written default (reviewed)")
if errors:
    print("\n".join(errors))
    sys.exit(1)
plan = plan.model_copy(update={"created_at": "2026-09-15T00:00:00Z"})
path = sys.argv[1]
write_plan(approve(plan), path)
print(f"wrote {path}: {len(plan.checks)} checks, {len(plan.judgement_tasks)} tasks, agents={[a.id for a in plan.agents]}")
