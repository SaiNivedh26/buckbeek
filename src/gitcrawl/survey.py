"""The zero-token pass: walk the tree once, set presence flags, fire early
clamps, and produce a ranked candidate shortlist. Runs before any model
call. See docs/design.md §2 stage 2 and §5.1.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from gitcrawl.config import get_config
from gitcrawl.models import RepoHandle, Survey
from gitcrawl.ranking import rank_candidates
from gitcrawl.tools.filters import is_excluded_dir, is_excluded_file

_TEST_PATH_RE = re.compile(
    r"(^|/)(tests?|__tests__|spec)(/|$)|(^|/)test_[^/]+\.\w+$|_test\.\w+$|\.test\.\w+$|\.spec\.\w+$",
    re.IGNORECASE,
)
_CI_PATH_RE = re.compile(
    r"^\.github/workflows/.+\.ya?ml$"
    r"|^\.gitlab-ci\.ya?ml$"
    r"|^\.circleci/config\.ya?ml$"
    r"|^Jenkinsfile$"
    r"|^\.travis\.ya?ml$"
    r"|^azure-pipelines\.ya?ml$",
    re.IGNORECASE,
)


def _root_file_prefix(files: list[str], prefix: str) -> bool:
    return any(f.upper().startswith(prefix) for f in files)


def _count_files_under(dir_path: str) -> int:
    """Count files under a pruned directory via metadata-only traversal —
    directory entries, never file content."""
    count = 0
    for _dirpath, _dirnames, filenames in os.walk(dir_path):
        count += len(filenames)
    return count


def run_survey(handle: RepoHandle) -> Survey:
    cfg = get_config()
    root = Path(handle.root)

    candidates: list[str] = []
    root_level_files: list[str] = []
    total_files = 0
    excluded_count = 0
    has_tests = False
    has_ci = False

    for dirpath, dirnames, filenames in os.walk(root):
        pruned = [d for d in dirnames if is_excluded_dir(d)]
        for d in pruned:
            # Directory listing only — no file content is ever read for a
            # pruned tree, but we still count what we skipped so the scope
            # log (§5.6) can report an honest number.
            n = _count_files_under(os.path.join(dirpath, d))
            excluded_count += n
            total_files += n
        dirnames[:] = [d for d in dirnames if not is_excluded_dir(d)]
        rel_dir = os.path.relpath(dirpath, root)

        for fname in filenames:
            total_files += 1
            rel_path = fname if rel_dir == "." else f"{rel_dir}/{fname}"
            rel_path = rel_path.replace(os.sep, "/")

            if rel_dir == ".":
                root_level_files.append(fname)

            if is_excluded_file(fname):
                excluded_count += 1
                continue

            candidates.append(rel_path)
            if _TEST_PATH_RE.search(rel_path):
                has_tests = True
            if _CI_PATH_RE.search(rel_path):
                has_ci = True

    has_readme = _root_file_prefix(root_level_files, "README")
    has_license = _root_file_prefix(root_level_files, "LICENSE") or _root_file_prefix(
        root_level_files, "LICENCE"
    )
    has_contributing = _root_file_prefix(root_level_files, "CONTRIBUTING")
    has_changelog = _root_file_prefix(root_level_files, "CHANGELOG") or _root_file_prefix(
        root_level_files, "HISTORY"
    )

    early_clamps: dict[str, float] = {}
    if not has_tests:
        early_clamps["test_coverage"] = cfg.clamps.no_tests_max
    if not has_ci:
        early_clamps["ci_cd"] = cfg.clamps.no_ci_max
    if not has_readme and not has_license:
        early_clamps["community"] = cfg.clamps.no_readme_no_license_max

    ranked = rank_candidates(root, candidates, limit=cfg.budget.shortlist_size)

    return Survey(
        root=str(root),
        commit_sha=handle.commit_sha,
        total_files=total_files,
        candidate_files=ranked,
        excluded_count=excluded_count,
        has_tests=has_tests,
        has_ci=has_ci,
        has_readme=has_readme,
        has_license=has_license,
        has_contributing=has_contributing,
        has_changelog=has_changelog,
        early_clamps=early_clamps,
    )
