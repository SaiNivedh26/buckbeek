"""GitHub drill-down tools for judgement agents: read one issue, pull request
or release in full, when the aggregate facts can't answer a quality question
("is the discussion constructive?", "are release notes meaningful?").

Same rules as the repo tools: metered against the agent's budget, failed
calls recorded, every read logged for citation checking ("issues/12",
"pulls/7", "releases/v1.2.0"), and all content wrapped as untrusted — issue
text is written by strangers and is a prompt-injection surface.

These are async tools, so their hooks are async too: Agno awaits an async
hook, while a sync hook around an async tool would hand back an un-awaited
coroutine.
"""

from __future__ import annotations

import inspect

from agno.tools import tool
from agno.tools.function import Function

from gitcrawl.collectors.base import CollectorError
from gitcrawl.github import queries
from gitcrawl.models import RepoHandle
from gitcrawl.tools.repo_tools import BUDGET_EXHAUSTED_MARKER, ToolContext, _meter
from gitcrawl.tools.wrapping import wrap_untrusted

_BODY_CHARS = 1500
_COMMENT_CHARS = 500


def _clip(text: str | None, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " […truncated]"


def _hooks(ctx: ToolContext, limiter):
    async def hook(function_name: str, func, arguments: dict):
        if limiter is not None:
            await limiter.acquire()
        try:
            result = func(**arguments)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception:
            ctx.ledger.record_failed_call(ctx.pillar)
            raise

    return [hook]


def build_github_tools(ctx: ToolContext, handle: RepoHandle, github, limiter=None) -> list[Function]:
    hooks = _hooks(ctx, limiter)
    base = {"owner": handle.owner, "name": handle.name}

    async def _query(query: str, **variables):
        try:
            data = await github.graphql(query, {**base, **variables})
        except CollectorError as e:
            return None, f"ERROR: {e}"
        return (data.get("repository") or {}), None

    @tool(name="get_issue_thread", description="Read one GitHub issue with its first comments.", tool_hooks=hooks)
    async def get_issue_thread(number: int) -> str:
        """Read a GitHub issue: title, state, labels, body and up to 10
        comments (each marked with the commenter's role). Takes ONLY the one
        argument listed below.

        Args:
            number: The issue number, e.g. one from the sample_issue_numbers fact.
        """
        if not _meter(ctx):
            return BUDGET_EXHAUSTED_MARKER
        repo, err = await _query(queries.ISSUE_THREAD, number=number)
        if err:
            return err
        issue = repo.get("issue")
        if issue is None:
            return f"ERROR: issue #{number} not found"
        ctx.ledger.record_read(ctx.pillar, f"issues/{number}")
        lines = [
            f"Issue #{issue['number']}: {issue['title']}",
            f"state={issue['state']} opened={issue['createdAt']} closed={issue.get('closedAt')} "
            f"author_role={issue['authorAssociation']}",
            "labels: " + ", ".join(n["name"] for n in issue["labels"]["nodes"]),
            "",
            _clip(issue.get("body"), _BODY_CHARS),
            "",
            f"comments ({issue['comments']['totalCount']} total, first 10):",
        ]
        for c in issue["comments"]["nodes"]:
            lines.append(f"- [{c['authorAssociation']} {c['createdAt']}] {_clip(c.get('body'), _COMMENT_CHARS)}")
        return wrap_untrusted(f"issues/{number}", "\n".join(lines))

    @tool(
        name="get_pull_request_thread",
        description="Read one GitHub pull request with its reviews and first comments.",
        tool_hooks=hooks,
    )
    async def get_pull_request_thread(number: int) -> str:
        """Read a GitHub pull request: title, state, size, body, up to 10
        reviews and 10 comments (each marked with the author's role). Takes
        ONLY the one argument listed below.

        Args:
            number: The pull request number, e.g. one from the sample_pull_request_numbers fact.
        """
        if not _meter(ctx):
            return BUDGET_EXHAUSTED_MARKER
        repo, err = await _query(queries.PULL_REQUEST_THREAD, number=number)
        if err:
            return err
        pr = repo.get("pullRequest")
        if pr is None:
            return f"ERROR: pull request #{number} not found"
        ctx.ledger.record_read(ctx.pillar, f"pulls/{number}")
        lines = [
            f"Pull request #{pr['number']}: {pr['title']}",
            f"state={pr['state']} opened={pr['createdAt']} merged={pr.get('mergedAt')} "
            f"author_role={pr['authorAssociation']} +{pr['additions']}/-{pr['deletions']}",
            "",
            _clip(pr.get("body"), _BODY_CHARS),
            "",
            f"reviews ({pr['reviews']['totalCount']} total):",
        ]
        for r in pr["reviews"]["nodes"]:
            meta = f"{r['authorAssociation']} {r['state']} {r['submittedAt']}"
            lines.append(f"- [{meta}] {_clip(r.get('body'), _COMMENT_CHARS)}")
        lines.append(f"comments ({pr['comments']['totalCount']} total, first 10):")
        for c in pr["comments"]["nodes"]:
            lines.append(f"- [{c['authorAssociation']} {c['createdAt']}] {_clip(c.get('body'), _COMMENT_CHARS)}")
        return wrap_untrusted(f"pulls/{number}", "\n".join(lines))

    @tool(name="get_release_notes", description="Read the notes of one GitHub release.", tool_hooks=hooks)
    async def get_release_notes(tag: str) -> str:
        """Read a GitHub release's notes. Takes ONLY the one argument listed below.

        Args:
            tag: The release tag, e.g. one from the recent_tags fact.
        """
        if not _meter(ctx):
            return BUDGET_EXHAUSTED_MARKER
        repo, err = await _query(queries.RELEASE_BY_TAG, tag=tag)
        if err:
            return err
        release = repo.get("release")
        if release is None:
            return f"ERROR: release {tag!r} not found"
        ctx.ledger.record_read(ctx.pillar, f"releases/{tag}")
        title = f"Release {release['tagName']} ({release.get('name') or ''})"
        text = f"{title} published {release.get('publishedAt')}\n\n" + _clip(release.get("description"), 3000)
        return wrap_untrusted(f"releases/{tag}", text)

    return [get_issue_thread, get_pull_request_thread, get_release_notes]
