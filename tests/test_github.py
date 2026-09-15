"""GitHub client and collectors against recorded-shape responses via
httpx.MockTransport — no network."""

import json
from datetime import UTC, datetime

import httpx
import pytest

from gitcrawl.collectors import CheckRequest, CollectorContext, RepoFiles, run_check
from gitcrawl.config import get_config
from gitcrawl.github.client import GitHubClient, GitHubError, GitHubNotFound, GitHubRateLimited
from gitcrawl.models import RepoHandle

NOW = datetime(2026, 9, 15, tzinfo=UTC)

OVERVIEW = {
    "repository": {
        "nameWithOwner": "acme/widget",
        "stargazerCount": 120,
        "forkCount": 14,
        "isArchived": False,
        "isFork": False,
        "createdAt": "2024-09-15T00:00:00Z",
        "pushedAt": "2026-09-13T00:00:00Z",
        "hasIssuesEnabled": True,
        "watchers": {"totalCount": 9},
        "licenseInfo": {"spdxId": "MIT"},
        "defaultBranchRef": {"name": "main", "target": {"history": {"totalCount": 42}}},
        "openIssues": {"totalCount": 10},
        "closedIssues": {"totalCount": 30},
        "openPRs": {"totalCount": 2},
        "mergedPRs": {"totalCount": 45},
        "closedPRs": {"totalCount": 5},
        "labels": {"totalCount": 12},
        "milestones": {"totalCount": 1},
        "releases": {"totalCount": 7},
    }
}

OLDEST_OPEN = {
    "repository": {
        "issues": {
            "nodes": [
                {"number": 3, "createdAt": "2025-01-01T00:00:00Z", "updatedAt": "2025-02-01T00:00:00Z"},
                {"number": 8, "createdAt": "2026-08-01T00:00:00Z", "updatedAt": "2026-09-01T00:00:00Z"},
            ]
        }
    }
}

RECENT_ISSUES = {
    "repository": {
        "issues": {
            "nodes": [
                {  # external issue, maintainer replied after 24h, closed after 2 days
                    "number": 40,
                    "state": "CLOSED",
                    "createdAt": "2026-09-01T00:00:00Z",
                    "closedAt": "2026-09-03T00:00:00Z",
                    "authorAssociation": "NONE",
                    "labels": {"totalCount": 1},
                    "milestone": None,
                    "comments": {"nodes": [{"createdAt": "2026-09-02T00:00:00Z", "authorAssociation": "OWNER"}]},
                },
                {  # external issue, nobody replied
                    "number": 41,
                    "state": "OPEN",
                    "createdAt": "2026-09-05T00:00:00Z",
                    "closedAt": None,
                    "authorAssociation": "CONTRIBUTOR",
                    "labels": {"totalCount": 0},
                    "milestone": {"number": 1},
                    "comments": {"nodes": [{"createdAt": "2026-09-06T00:00:00Z", "authorAssociation": "NONE"}]},
                },
            ]
        }
    }
}

RECENT_PRS = {
    "repository": {
        "pullRequests": {
            "nodes": [
                {
                    "number": 50,
                    "state": "MERGED",
                    "createdAt": "2026-09-01T00:00:00Z",
                    "mergedAt": "2026-09-02T00:00:00Z",
                    "closedAt": "2026-09-02T00:00:00Z",
                    "authorAssociation": "NONE",
                    "labels": {"totalCount": 0},
                    "reviews": {
                        "totalCount": 1,
                        "nodes": [
                            {
                                "submittedAt": "2026-09-01T06:00:00Z",
                                "authorAssociation": "MEMBER",
                                "state": "APPROVED",
                            }
                        ],
                    },
                    "comments": {"nodes": []},
                },
                {
                    "number": 51,
                    "state": "MERGED",
                    "createdAt": "2026-09-03T00:00:00Z",
                    "mergedAt": "2026-09-03T12:00:00Z",
                    "closedAt": "2026-09-03T12:00:00Z",
                    "authorAssociation": "OWNER",
                    "labels": {"totalCount": 0},
                    "reviews": {"totalCount": 0, "nodes": []},
                    "comments": {"nodes": []},
                },
            ]
        }
    }
}

RELEASES = {
    "repository": {
        "releases": {
            "nodes": [
                {
                    "tagName": "v1.2.0",
                    "name": "",
                    "publishedAt": "2026-09-01T00:00:00Z",
                    "createdAt": "2026-09-01T00:00:00Z",
                    "isPrerelease": False,
                    "isDraft": False,
                    "description": "Adds retries, fixes #40 and improves the docs.",
                },
                {
                    "tagName": "v1.1.0",
                    "name": "",
                    "publishedAt": "2026-07-01T00:00:00Z",
                    "createdAt": "2026-07-01T00:00:00Z",
                    "isPrerelease": False,
                    "isDraft": False,
                    "description": "",
                },
                {
                    "tagName": "v1.0.0",
                    "name": "",
                    "publishedAt": "2025-05-01T00:00:00Z",
                    "createdAt": "2025-05-01T00:00:00Z",
                    "isPrerelease": False,
                    "isDraft": False,
                    "description": "First stable release with a full changelog.",
                },
            ]
        }
    }
}

CONTRIBUTORS = [
    {"login": "alice", "type": "User", "contributions": 80},
    {"login": "bob", "type": "User", "contributions": 15},
    {"login": "carol", "type": "User", "contributions": 5},
    {"login": "dependabot[bot]", "type": "Bot", "contributions": 300},
]

RUNS = {
    "workflow_runs": [
        {
            "status": "completed",
            "conclusion": "failure",
            "run_attempt": 1,
            "event": "push",
            "head_branch": "main",
            "created_at": "2026-09-14T00:00:00Z",
        },
        {
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 2,
            "event": "push",
            "head_branch": "main",
            "created_at": "2026-09-13T00:00:00Z",
        },
        {
            "status": "completed",
            "conclusion": "success",
            "run_attempt": 1,
            "event": "pull_request",
            "head_branch": "feature",
            "created_at": "2026-09-12T00:00:00Z",
        },
        {
            "status": "completed",
            "conclusion": "cancelled",
            "run_attempt": 1,
            "event": "push",
            "head_branch": "main",
            "created_at": "2026-09-11T00:00:00Z",
        },
    ]
}

GRAPHQL = {
    "RepoOverview": OVERVIEW,
    "OldestOpenIssues": OLDEST_OPEN,
    "RecentIssues": RECENT_ISSUES,
    "RecentPullRequests": RECENT_PRS,
    "RecentReleases": RELEASES,
}


def api_handler(calls: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/graphql":
            query = json.loads(request.content)["query"]
            name = next(n for n in GRAPHQL if f"query {n}(" in query)
            calls.append(name)
            return httpx.Response(200, json={"data": GRAPHQL[name]})
        calls.append(request.url.path)
        if request.url.path.endswith("/contributors"):
            return httpx.Response(200, json=CONTRIBUTORS)
        if request.url.path.endswith("/actions/runs"):
            return httpx.Response(200, json=RUNS)
        return httpx.Response(404, json={"message": "Not Found"})

    return handler


def _client(handler, sleeps=None) -> GitHubClient:
    async def sleep(s):
        if sleeps is not None:
            sleeps.append(s)

    return GitHubClient("t0ken", get_config(), transport=httpx.MockTransport(handler), sleep=sleep)


def _ctx(tmp_path, client) -> CollectorContext:
    handle = RepoHandle(root=str(tmp_path), origin="https://github.com/acme/widget", commit_sha="abc",
                        owner="acme", name="widget")  # fmt: skip
    ctx = CollectorContext(handle=handle, cfg=get_config(), files=RepoFiles(tmp_path), github=client)
    ctx.memo["now"] = NOW
    return ctx


async def _collect(tmp_path, collector_name):
    calls: list[str] = []
    client = _client(api_handler(calls))
    fact = await run_check(CheckRequest("x", collector_name), _ctx(tmp_path, client))
    assert fact.ok, fact.error
    return fact.data, calls


async def test_repo_collector(tmp_path):
    data, _ = await _collect(tmp_path, "github.repo")
    assert data["stars"] == 120 and data["license"] == "MIT"
    assert data["days_since_last_push"] == 2.0
    assert data["commits_last_90_days"] == 42


async def test_issues_collector_counts_only_maintainer_responses_to_external_issues(tmp_path):
    data, calls = await _collect(tmp_path, "github.issues")
    assert data["close_rate"] == 0.75
    assert data["stale_open_share"] == 0.5  # #3 untouched since Feb 2025
    assert data["median_days_to_close"] == 2.0
    assert data["maintainer_response_share"] == 0.5
    assert data["median_hours_to_first_maintainer_response"] == 24.0
    assert data["labelled_share"] == 0.5 and data["milestone_share"] == 0.5
    assert 3 in data["sample_issue_numbers"]
    assert calls.count("RepoOverview") == 1


async def test_pull_requests_collector(tmp_path):
    data, _ = await _collect(tmp_path, "github.pull_requests")
    assert data["merge_rate"] == 0.9
    assert data["reviewed_before_merge_share"] == 0.5
    assert data["merged_without_review_share"] == 0.5
    assert data["median_hours_to_first_review"] == 6.0
    assert data["external_pr_response_share"] == 1.0


async def test_contributors_collector_ignores_bots(tmp_path):
    data, _ = await _collect(tmp_path, "github.contributors")
    assert data["contributor_count"] == 3
    assert data["top_contributor_share"] == 0.8
    assert data["contributors_with_10_plus_commits"] == 2


async def test_releases_collector(tmp_path):
    data, _ = await _collect(tmp_path, "github.releases")
    assert data["latest_release_tag"] == "v1.2.0"
    assert data["latest_release_days_ago"] == 14.0
    assert data["releases_last_365_days"] == 2
    assert data["with_notes_share"] == pytest.approx(0.667)


async def test_workflow_runs_collector(tmp_path):
    data, _ = await _collect(tmp_path, "github.workflow_runs")
    assert data["completed_runs"] == 3  # cancelled excluded
    assert data["success_rate"] == pytest.approx(0.667)
    assert data["first_attempt_success_rate"] == pytest.approx(0.333)
    assert data["default_branch_failure_streak"] == 1
    assert data["pull_request_run_share"] == 0.25


async def test_memoizes_identical_requests():
    calls: list[str] = []
    client = _client(api_handler(calls))
    for _ in range(3):
        await client.graphql("query RepoOverview($owner: String!) { x }", {"owner": "acme"})
    assert calls == ["RepoOverview"] and client.requests == 1


async def test_rate_limit_waits_for_retry_after_then_succeeds():
    sleeps: list[float] = []
    attempts = {"n": 0}

    def handler(request):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return httpx.Response(403, headers={"retry-after": "7"}, json={"message": "secondary rate limit"})
        return httpx.Response(200, json={"ok": True})

    client = _client(handler, sleeps)
    assert await client.rest("/rate") == {"ok": True}
    assert sleeps == [7.0]


async def test_long_rate_limit_fails_clearly_instead_of_hanging():
    def handler(request):
        return httpx.Response(429, headers={"retry-after": "3600"}, json={"message": "rate limited"})

    with pytest.raises(GitHubRateLimited, match="rate limit"):
        await _client(handler).rest("/slow")


async def test_errors_are_typed():
    def handler(request):
        if request.url.path == "/bad-token":
            return httpx.Response(401, json={"message": "Bad credentials"})
        return httpx.Response(200, json={"errors": [{"type": "NOT_FOUND", "message": "Could not resolve"}]})

    client = _client(handler)
    with pytest.raises(GitHubError, match="rejected the token"):
        await client.rest("/bad-token")
    with pytest.raises(GitHubNotFound):
        await client.graphql("query X { y }", {})


async def test_github_error_becomes_unavailable_fact(tmp_path):
    def handler(request):
        return httpx.Response(401, json={"message": "Bad credentials"})

    fact = await run_check(CheckRequest("r", "github.repo"), _ctx(tmp_path, _client(handler)))
    assert not fact.ok and "rejected the token" in fact.error


async def test_evaluate_refuses_github_plan_without_token(monkeypatch):
    from test_engine import make_plan

    from gitcrawl.engine import PreflightError, evaluate

    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    plan, rubric = make_plan()
    plan.checks.append(plan.checks[0].model_copy(update={"id": "runs", "collector": "github.workflow_runs"}))
    plan.pillars[0].criteria[0].check_ids.append("runs")
    from gitcrawl.plan.io import approve

    with pytest.raises(PreflightError, match="GITHUB_TOKEN"):
        await evaluate("acme/widget", approve(plan), rubric)
