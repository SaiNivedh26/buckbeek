"""Agent grouping — computed by code, never proposed by the planner.

Judgement tasks are grouped by evidence domain: every task that needs the
same kind of material goes to one agent, so e.g. "are the tests meaningful?"
(Test Coverage) and "does CI run the real suite?" (CI/CD) don't each pay to
re-read the same files. Scorers stay one per pillar; isolation matters when
judging a score, not when gathering evidence.
"""

from __future__ import annotations

from gitcrawl.config import GitCrawlConfig
from gitcrawl.plan.models import EVIDENCE_DOMAINS, AgentSpec, JudgementTask

REPO_TOOLS = ("list_directory", "read_file", "search_repo")
GITHUB_TOOLS = ("get_issue_thread", "get_pull_request_thread", "get_release_notes")
KNOWN_TOOLS = frozenset(REPO_TOOLS + GITHUB_TOOLS)

DOMAIN_TOOLS: dict[str, tuple[str, ...]] = {
    "source_code": REPO_TOOLS,
    "tests": REPO_TOOLS,
    "ci": REPO_TOOLS,
    "docs_community": (*REPO_TOOLS, "get_release_notes"),
    "issues_prs": ("get_issue_thread", "get_pull_request_thread", "read_file"),
}


def compute_agents(tasks: list[JudgementTask], cfg: GitCrawlConfig) -> list[AgentSpec]:
    agents: list[AgentSpec] = []
    for domain in EVIDENCE_DOMAINS:
        task_ids = [t.id for t in tasks if t.evidence_domain == domain]
        if not task_ids:
            continue
        agents.append(
            AgentSpec(
                id=f"{domain}_agent",
                evidence_domain=domain,
                task_ids=task_ids,
                tools=list(DOMAIN_TOOLS[domain]),
                budget=cfg.agents.budgets.get(domain, cfg.agents.default_budget),
            )
        )
    return agents
