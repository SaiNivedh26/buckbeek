"""GitHub API collectors: rates, ratios and bounded windows — never full history.

Response-time metrics count only replies from maintainers (OWNER, MEMBER,
COLLABORATOR) to people who aren't, since a maintainer commenting on their
own issue says nothing about responsiveness.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from gitcrawl.collectors.base import CollectorContext, CollectorError, CollectorResult, collector
from gitcrawl.github import queries

MAINTAINER_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
_STALE_DAYS = 90


def _now(ctx: CollectorContext) -> datetime:
    return ctx.memo.get("now") or datetime.now(UTC)


def _ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _days(delta: timedelta) -> float:
    return round(delta.total_seconds() / 86400, 1)


def _hours(delta: timedelta) -> float:
    return round(delta.total_seconds() / 3600, 1)


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def _vars(ctx: CollectorContext, **extra: Any) -> dict[str, Any]:
    if not ctx.handle.owner:
        raise CollectorError("repository owner/name unknown — GitHub collectors need a GitHub repository")
    return {"owner": ctx.handle.owner, "name": ctx.handle.name, **extra}


async def _repository(ctx: CollectorContext, query: str, **extra: Any) -> dict[str, Any]:
    data = await ctx.github.graphql(query, _vars(ctx, **extra))
    repo = data.get("repository")
    if repo is None:
        raise CollectorError(f"GitHub repository {ctx.handle.full_name} not found or not accessible")
    return repo


async def _overview(ctx: CollectorContext) -> dict[str, Any]:
    since = (_now(ctx) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return await _repository(ctx, queries.REPO_OVERVIEW, since=since)


def _first_maintainer_reply(item: dict[str, Any]) -> datetime | None:
    replies = [
        _ts(n.get("submittedAt") or n.get("createdAt"))
        for key in ("comments", "reviews")
        for n in (item.get(key) or {}).get("nodes", [])
        if n.get("authorAssociation") in MAINTAINER_ASSOCIATIONS
    ]
    replies = [r for r in replies if r is not None]
    return min(replies) if replies else None


# --- github.repo -----------------------------------------------------------


class RepoOutput(BaseModel):
    stars: int
    forks: int
    watchers: int
    is_archived: bool
    is_fork: bool
    license: str | None
    has_issues_enabled: bool
    default_branch: str | None
    created_days_ago: float
    days_since_last_push: float | None
    commits_last_90_days: int | None
    open_issues: int
    closed_issues: int
    open_pull_requests: int
    merged_pull_requests: int
    closed_unmerged_pull_requests: int
    labels: int
    milestones: int
    releases: int


@collector(
    "github.repo",
    description=(
        "Repository totals from the GitHub API: stars, forks, watchers, archived/fork flags, license, "
        "issues enabled, age, days since last push, commits in the last 90 days, open/closed issue and PR "
        "counts, label, milestone and release counts."
    ),
    category="github",
    output=RepoOutput,
    requires_github=True,
)
async def github_repo(ctx: CollectorContext, params) -> CollectorResult:
    r = await _overview(ctx)
    now = _now(ctx)
    branch = r.get("defaultBranchRef") or {}
    history = ((branch.get("target") or {}).get("history") or {}).get("totalCount")
    pushed = _ts(r.get("pushedAt"))
    data = RepoOutput(
        stars=r["stargazerCount"],
        forks=r["forkCount"],
        watchers=r["watchers"]["totalCount"],
        is_archived=r["isArchived"],
        is_fork=r["isFork"],
        license=(r.get("licenseInfo") or {}).get("spdxId"),
        has_issues_enabled=r["hasIssuesEnabled"],
        default_branch=branch.get("name"),
        created_days_ago=_days(now - _ts(r["createdAt"])),
        days_since_last_push=_days(now - pushed) if pushed else None,
        commits_last_90_days=history,
        open_issues=r["openIssues"]["totalCount"],
        closed_issues=r["closedIssues"]["totalCount"],
        open_pull_requests=r["openPRs"]["totalCount"],
        merged_pull_requests=r["mergedPRs"]["totalCount"],
        closed_unmerged_pull_requests=r["closedPRs"]["totalCount"],
        labels=r["labels"]["totalCount"],
        milestones=r["milestones"]["totalCount"],
        releases=r["releases"]["totalCount"],
    )
    return CollectorResult(data=data, citations=[f"github:{ctx.handle.full_name}"])


# --- github.issues ---------------------------------------------------------


class IssuesOutput(BaseModel):
    open_issues: int
    closed_issues: int
    close_rate: float | None
    oldest_open_window: int
    stale_open_share: float | None  # share of the oldest-open window untouched for 90+ days
    oldest_open_issue_days: float | None
    recent_window: int
    median_days_to_close: float | None
    median_hours_to_first_maintainer_response: float | None
    maintainer_response_share: float | None  # recent external issues that got a maintainer reply
    labelled_share: float | None
    milestone_share: float | None
    sample_issue_numbers: list[int]


@collector(
    "github.issues",
    description=(
        "Issue health from the GitHub API: open/closed totals and close rate; staleness of the oldest open "
        "issues; for recent issues, median days to close, median hours to a maintainer's first response, "
        "share of external issues that got a maintainer response, and label/milestone usage; sample issue "
        "numbers for reading threads."
    ),
    category="github",
    output=IssuesOutput,
    requires_github=True,
)
async def github_issues(ctx: CollectorContext, params) -> CollectorResult:
    windows = ctx.cfg.api_windows
    now = _now(ctx)
    overview = await _overview(ctx)
    oldest = (await _repository(ctx, queries.OLDEST_OPEN_ISSUES, first=windows.oldest_open_issues))["issues"][
        "nodes"
    ]
    recent = (await _repository(ctx, queries.RECENT_ISSUES, first=windows.recent_issues))["issues"]["nodes"]

    open_n, closed_n = overview["openIssues"]["totalCount"], overview["closedIssues"]["totalCount"]
    stale = [i for i in oldest if now - _ts(i["updatedAt"]) > timedelta(days=_STALE_DAYS)]

    close_days = [_days(_ts(i["closedAt"]) - _ts(i["createdAt"])) for i in recent if i.get("closedAt")]
    external = [i for i in recent if i.get("authorAssociation") not in MAINTAINER_ASSOCIATIONS]
    response_hours = []
    responded = 0
    for issue in external:
        reply = _first_maintainer_reply(issue)
        if reply is not None:
            responded += 1
            response_hours.append(_hours(reply - _ts(issue["createdAt"])))

    data = IssuesOutput(
        open_issues=open_n,
        closed_issues=closed_n,
        close_rate=_share(closed_n, open_n + closed_n),
        oldest_open_window=len(oldest),
        stale_open_share=_share(len(stale), len(oldest)),
        oldest_open_issue_days=max((_days(now - _ts(i["createdAt"])) for i in oldest), default=None),
        recent_window=len(recent),
        median_days_to_close=_median(close_days),
        median_hours_to_first_maintainer_response=_median(response_hours),
        maintainer_response_share=_share(responded, len(external)),
        labelled_share=_share(sum(1 for i in recent if i["labels"]["totalCount"] > 0), len(recent)),
        milestone_share=_share(sum(1 for i in recent if i.get("milestone")), len(recent)),
        sample_issue_numbers=[i["number"] for i in recent[:5]] + [i["number"] for i in stale[:3]],
    )
    return CollectorResult(data=data, citations=[f"github:{ctx.handle.full_name}/issues"])


# --- github.pull_requests ----------------------------------------------------


class PullRequestsOutput(BaseModel):
    open_pull_requests: int
    merged_pull_requests: int
    closed_unmerged_pull_requests: int
    merge_rate: float | None
    recent_window: int
    median_hours_to_first_review: float | None
    reviewed_before_merge_share: float | None
    merged_without_review_share: float | None
    external_pr_response_share: float | None
    median_days_to_merge: float | None
    sample_pull_request_numbers: list[int]


@collector(
    "github.pull_requests",
    description=(
        "Pull request workflow from the GitHub API: open/merged/closed totals and merge rate; for recent PRs, "
        "median hours to a maintainer's first review or comment, share merged with vs. without a review, "
        "share of external PRs that got a maintainer response, median days to merge; sample PR numbers."
    ),
    category="github",
    output=PullRequestsOutput,
    requires_github=True,
)
async def github_pull_requests(ctx: CollectorContext, params) -> CollectorResult:
    overview = await _overview(ctx)
    prs = (await _repository(ctx, queries.RECENT_PULL_REQUESTS, first=ctx.cfg.api_windows.recent_prs))[
        "pullRequests"
    ]["nodes"]

    merged_n = overview["mergedPRs"]["totalCount"]
    closed_n = overview["closedPRs"]["totalCount"]
    merged = [p for p in prs if p.get("mergedAt")]
    reviewed_merged = [p for p in merged if p["reviews"]["totalCount"] > 0]
    review_hours, external, responded = [], 0, 0
    for pr in prs:
        is_external = pr.get("authorAssociation") not in MAINTAINER_ASSOCIATIONS
        reply = _first_maintainer_reply(pr)
        external += is_external
        if reply is not None:
            responded += is_external
            review_hours.append(_hours(reply - _ts(pr["createdAt"])))

    data = PullRequestsOutput(
        open_pull_requests=overview["openPRs"]["totalCount"],
        merged_pull_requests=merged_n,
        closed_unmerged_pull_requests=closed_n,
        merge_rate=_share(merged_n, merged_n + closed_n),
        recent_window=len(prs),
        median_hours_to_first_review=_median(review_hours),
        reviewed_before_merge_share=_share(len(reviewed_merged), len(merged)),
        merged_without_review_share=_share(len(merged) - len(reviewed_merged), len(merged)),
        external_pr_response_share=_share(responded, external),
        median_days_to_merge=_median([_days(_ts(p["mergedAt"]) - _ts(p["createdAt"])) for p in merged]),
        sample_pull_request_numbers=[p["number"] for p in prs[:5]],
    )
    return CollectorResult(data=data, citations=[f"github:{ctx.handle.full_name}/pulls"])


# --- github.contributors ------------------------------------------------------


class ContributorsOutput(BaseModel):
    contributor_count: int
    count_is_capped: bool  # the endpoint's first page holds 100; more may exist
    top_contributor_share: float | None
    top3_share: float | None
    contributors_with_10_plus_commits: int
    commits_last_90_days: int | None


@collector(
    "github.contributors",
    description=(
        "Contributor base from the GitHub API: number of contributors, share of commits by the top and top-3 "
        "contributors (bus factor), contributors with 10+ commits, commits in the last 90 days."
    ),
    category="github",
    output=ContributorsOutput,
    requires_github=True,
)
async def github_contributors(ctx: CollectorContext, params) -> CollectorResult:
    people = await ctx.github.rest(
        f"/repos/{ctx.handle.owner}/{ctx.handle.name}/contributors", params={"per_page": 100}
    )
    overview = await _overview(ctx)
    humans = [
        p for p in (people or []) if p.get("type") != "Bot" and not str(p.get("login", "")).endswith("[bot]")
    ]
    counts = sorted((p.get("contributions", 0) for p in humans), reverse=True)
    total = sum(counts)
    history = (((overview.get("defaultBranchRef") or {}).get("target") or {}).get("history") or {}).get(
        "totalCount"
    )
    data = ContributorsOutput(
        contributor_count=len(humans),
        count_is_capped=len(people or []) >= 100,
        top_contributor_share=_share(counts[0], total) if counts else None,
        top3_share=_share(sum(counts[:3]), total) if counts else None,
        contributors_with_10_plus_commits=sum(1 for c in counts if c >= 10),
        commits_last_90_days=history,
    )
    return CollectorResult(data=data, citations=[f"github:{ctx.handle.full_name}/contributors"])


# --- github.releases -----------------------------------------------------------


class ReleasesOutput(BaseModel):
    release_count: int
    recent_window: int
    latest_release_tag: str | None
    latest_release_days_ago: float | None
    releases_last_365_days: int
    median_days_between_releases: float | None
    with_notes_share: float | None
    recent_tags: list[str]


@collector(
    "github.releases",
    description=(
        "Release cadence from the GitHub API: total releases, latest release and its age, releases in the last "
        "365 days, median days between recent releases, share of recent releases with written notes, recent tags."
    ),
    category="github",
    output=ReleasesOutput,
    requires_github=True,
)
async def github_releases(ctx: CollectorContext, params) -> CollectorResult:
    now = _now(ctx)
    overview = await _overview(ctx)
    nodes = (await _repository(ctx, queries.RECENT_RELEASES, first=ctx.cfg.api_windows.recent_releases))[
        "releases"
    ]["nodes"]
    published = [r for r in nodes if not r.get("isDraft")]
    dates = sorted((_ts(r.get("publishedAt") or r["createdAt"]) for r in published), reverse=True)
    gaps = [_days(a - b) for a, b in zip(dates, dates[1:], strict=False)]
    data = ReleasesOutput(
        release_count=overview["releases"]["totalCount"],
        recent_window=len(published),
        latest_release_tag=published[0]["tagName"] if published else None,
        latest_release_days_ago=_days(now - dates[0]) if dates else None,
        releases_last_365_days=sum(1 for d in dates if now - d <= timedelta(days=365)),
        median_days_between_releases=_median(gaps),
        with_notes_share=_share(
            sum(1 for r in published if len((r.get("description") or "").strip()) >= 40), len(published)
        ),
        recent_tags=[r["tagName"] for r in published],
    )
    return CollectorResult(data=data, citations=[f"github:{ctx.handle.full_name}/releases"])


# --- github.workflow_runs --------------------------------------------------------


class WorkflowRunsOutput(BaseModel):
    has_runs: bool
    runs_sampled: int
    completed_runs: int
    success_rate: float | None
    first_attempt_success_rate: float | None
    default_branch_success_rate: float | None
    pull_request_run_share: float | None
    last_run_days_ago: float | None
    default_branch_failure_streak: int  # consecutive most-recent failed runs on the default branch


@collector(
    "github.workflow_runs",
    description=(
        "CI run history from GitHub Actions (most recent runs): success rate, first-attempt success rate, "
        "default-branch success rate and current failure streak, share of runs triggered by pull requests, "
        "days since the last run."
    ),
    category="github",
    output=WorkflowRunsOutput,
    requires_github=True,
)
async def github_workflow_runs(ctx: CollectorContext, params) -> CollectorResult:
    now = _now(ctx)
    body = await ctx.github.rest(
        f"/repos/{ctx.handle.owner}/{ctx.handle.name}/actions/runs",
        params={"per_page": ctx.cfg.api_windows.recent_workflow_runs},
    )
    runs = body.get("workflow_runs", []) if isinstance(body, dict) else []
    overview = await _overview(ctx)
    default_branch = (overview.get("defaultBranchRef") or {}).get("name")

    completed = [
        r for r in runs if r.get("status") == "completed" and r.get("conclusion") not in ("skipped", "cancelled")
    ]
    ok = [r for r in completed if r.get("conclusion") == "success"]
    first_try_ok = [r for r in ok if r.get("run_attempt", 1) == 1]
    on_default = [
        r for r in completed if r.get("head_branch") == default_branch and r.get("event") != "pull_request"
    ]
    streak = 0
    for r in sorted(on_default, key=lambda r: r["created_at"], reverse=True):
        if r.get("conclusion") == "success":
            break
        streak += 1
    latest = max((_ts(r["created_at"]) for r in runs), default=None)
    data = WorkflowRunsOutput(
        has_runs=bool(runs),
        runs_sampled=len(runs),
        completed_runs=len(completed),
        success_rate=_share(len(ok), len(completed)),
        first_attempt_success_rate=_share(len(first_try_ok), len(completed)),
        default_branch_success_rate=_share(
            sum(1 for r in on_default if r.get("conclusion") == "success"), len(on_default)
        ),
        pull_request_run_share=_share(sum(1 for r in runs if r.get("event") == "pull_request"), len(runs)),
        last_run_days_ago=_days(now - latest) if latest else None,
        default_branch_failure_streak=streak,
    )
    return CollectorResult(data=data, citations=[f"github:{ctx.handle.full_name}/actions"])
