"""Deterministic collectors. Importing this package registers every
built-in collector in `REGISTRY` — the catalog the planner chooses from."""

from gitcrawl.collectors import ci, code, generic, github_api, inventory, tests  # noqa: F401  (registration)
from gitcrawl.collectors.base import (
    REGISTRY,
    CheckRequest,
    CollectorContext,
    CollectorError,
    CollectorResult,
    CollectorSpec,
    Fact,
    collector,
    run_check,
    validate_check,
)
from gitcrawl.collectors.files import RepoFiles, glob_match
from gitcrawl.collectors.runner import collect, default_requests

__all__ = [
    "REGISTRY",
    "CheckRequest",
    "CollectorContext",
    "CollectorError",
    "CollectorResult",
    "CollectorSpec",
    "Fact",
    "RepoFiles",
    "collect",
    "collector",
    "default_requests",
    "glob_match",
    "run_check",
    "validate_check",
]
