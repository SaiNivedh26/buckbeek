"""repo.inventory: the zero-token file walk (formerly survey.py's job)."""

from __future__ import annotations

from pydantic import BaseModel

from gitcrawl.collectors.base import CollectorContext, CollectorResult, collector
from gitcrawl.ranking import rank_candidates


class InventoryOutput(BaseModel):
    total_files: int
    candidate_files: int
    excluded_files: int
    top_level_dirs: list[str]
    has_readme: bool
    has_license: bool
    has_contributing: bool
    has_changelog: bool
    has_code_of_conduct: bool
    has_security_policy: bool
    has_issue_templates: bool
    has_pr_template: bool
    ranked_shortlist: list[str]


# Where GitHub itself looks for community health files.
_COMMUNITY_DIRS = ("", ".github/", "docs/")


def _find(files: list[str], prefixes: tuple[str, ...]) -> list[str]:
    hits = []
    for f in files:
        lower = f.lower()
        for d in _COMMUNITY_DIRS:
            if not lower.startswith(d):
                continue
            rest = lower[len(d) :]
            if "/" not in rest and rest.startswith(prefixes):
                hits.append(f)
    return hits


@collector(
    "repo.inventory",
    description=(
        "File inventory after excluding vendored/generated/binary files, plus presence of README, LICENSE, "
        "CONTRIBUTING, CHANGELOG, CODE_OF_CONDUCT, SECURITY policy, issue templates and PR template."
    ),
    category="files",
    output=InventoryOutput,
)
def repo_inventory(ctx: CollectorContext, params) -> CollectorResult:
    inv = ctx.files.inventory()
    files = inv.files
    lower = [f.lower() for f in files]

    readme = [f for f in inv.root_files if f.lower().startswith("readme")]
    license_ = [f for f in inv.root_files if f.lower().startswith(("license", "licence", "copying"))]
    contributing = _find(files, ("contributing",))
    changelog = [f for f in inv.root_files if f.lower().startswith(("changelog", "history", "changes"))]
    coc = _find(files, ("code_of_conduct", "code-of-conduct"))
    security = _find(files, ("security",))
    issue_templates = [f for f, lo in zip(files, lower, strict=True) if lo.startswith(".github/issue_template")]
    pr_template = [f for f, lo in zip(files, lower, strict=True) if "pull_request_template" in lo]

    shortlist = rank_candidates(ctx.files.root, files, limit=20)
    data = InventoryOutput(
        total_files=inv.total_files,
        candidate_files=len(files),
        excluded_files=inv.excluded_count,
        top_level_dirs=inv.top_level_dirs,
        has_readme=bool(readme),
        has_license=bool(license_),
        has_contributing=bool(contributing),
        has_changelog=bool(changelog),
        has_code_of_conduct=bool(coc),
        has_security_policy=bool(security),
        has_issue_templates=bool(issue_templates),
        has_pr_template=bool(pr_template),
        ranked_shortlist=shortlist,
    )
    citations = readme + license_ + contributing + changelog + coc + security + issue_templates + pr_template
    return CollectorResult(data=data, citations=citations)
