"""Collector framework: the deterministic half of an evaluation.

A collector is tested Python code that turns a repository (or its GitHub API
data) into facts. The planner model never writes collectors; it can only
pick them from the catalog and fill in their parameters, which are validated
against each collector's own params model before a plan is accepted. That is
what "deterministic agents" means in this design — see docs/design.md.

Every failure becomes an explicit `Fact.error`, logged, never fabricated
data: "no tests exist" and "the test collector crashed" must never look alike.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, ValidationError

if TYPE_CHECKING:
    from gitcrawl.collectors.files import RepoFiles
    from gitcrawl.config import GitCrawlConfig
    from gitcrawl.github.client import GitHubClient
    from gitcrawl.models import RepoHandle

logger = logging.getLogger(__name__)

CollectorCategory = Literal["files", "ci", "tests", "code", "github"]
COLLECTOR_CATEGORIES: tuple[str, ...] = get_args(CollectorCategory)


class CollectorError(Exception):
    """An expected, explainable failure (missing token, unparseable file).
    Reported as the fact's error text; anything else is logged with a trace."""


class NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Fact(BaseModel):
    """One check's result. `data` matches the collector's output model."""

    check_id: str
    collector: str
    params: dict[str, Any] = {}
    data: dict[str, Any] = {}
    citations: list[str] = []
    error: str | None = None
    cached: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class CollectorResult:
    data: BaseModel
    citations: list[str] = field(default_factory=list)


@dataclass
class CollectorContext:
    handle: RepoHandle
    cfg: GitCrawlConfig
    files: RepoFiles
    github: GitHubClient | None = None
    # Per-run memo for expensive shared parses (e.g. workflow files read by
    # both the CI and test collectors), keyed by whatever the helper chooses.
    memo: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CollectorSpec:
    name: str
    description: str
    category: CollectorCategory
    version: str
    params_model: type[BaseModel]
    output_model: type[BaseModel]
    func: Callable[..., Any]
    requires_github: bool

    def output_fields(self) -> dict[str, str]:
        return {
            name: _type_label(f.annotation) for name, f in self.output_model.model_fields.items()
        }

    def param_fields(self) -> dict[str, str]:
        return {name: _type_label(f.annotation) for name, f in self.params_model.model_fields.items()}

    def has_required_params(self) -> bool:
        return any(f.is_required() for f in self.params_model.model_fields.values())


def _type_label(annotation: Any) -> str:
    text = getattr(annotation, "__name__", None) or str(annotation)
    return text.replace("typing.", "")


REGISTRY: dict[str, CollectorSpec] = {}


def collector(
    name: str,
    *,
    description: str,
    category: CollectorCategory,
    output: type[BaseModel],
    params: type[BaseModel] = NoParams,
    version: str = "1",
    requires_github: bool = False,
):
    """Register a collector. The function receives (ctx, params) and returns
    a CollectorResult (sync or async)."""

    def deco(func):
        if name in REGISTRY:
            raise ValueError(f"collector {name!r} registered twice")
        REGISTRY[name] = CollectorSpec(
            name=name,
            description=description,
            category=category,
            version=version,
            params_model=params,
            output_model=output,
            func=func,
            requires_github=requires_github,
        )
        return func

    return deco


def catalog_version() -> str:
    """Fingerprint of every registered collector's name, version and fields."""
    payload = sorted(
        (s.name, s.version, sorted(s.param_fields().items()), sorted(s.output_fields().items()))
        for s in REGISTRY.values()
    )
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:12]


def params_hash(params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class CheckRequest:
    """One configured use of a collector, as it appears in a plan."""

    id: str
    collector: str
    params: dict[str, Any] = field(default_factory=dict)


def validate_check(collector_name: str, params: dict[str, Any]) -> list[str]:
    """Plan-time validation: the collector exists and the params fit its model."""
    spec = REGISTRY.get(collector_name)
    if spec is None:
        return [f"unknown collector {collector_name!r}"]
    try:
        spec.params_model.model_validate(params)
    except ValidationError as e:
        return [
            f"{collector_name}: invalid param {'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
            for err in e.errors()
        ]
    return []


async def run_check(req: CheckRequest, ctx: CollectorContext) -> Fact:
    base = {"check_id": req.id, "collector": req.collector, "params": req.params}
    spec = REGISTRY.get(req.collector)
    if spec is None:
        return Fact(**base, error=f"unknown collector {req.collector!r}")

    try:
        params = spec.params_model.model_validate(req.params)
    except ValidationError as e:
        return Fact(**base, error=f"invalid params: {e.errors()[0]['msg']}")

    if spec.requires_github and ctx.github is None:
        return Fact(**base, error="needs GitHub API access, but no GitHub token is configured")

    try:
        result = spec.func(ctx, params)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, CollectorResult) or not isinstance(result.data, spec.output_model):
            raise TypeError(f"collector {req.collector!r} returned {type(result).__name__}, not its output model")
    except CollectorError as e:
        logger.warning("collector %s (check %s) could not run: %s", req.collector, req.id, e)
        return Fact(**base, error=str(e))
    except Exception as e:
        # A failed collector degrades to an explicit error fact — never
        # silently, and never as fabricated data.
        logger.exception("collector %s (check %s) failed", req.collector, req.id)
        return Fact(**base, error=f"collector crashed: {type(e).__name__}: {e}")

    return Fact(**base, data=result.data.model_dump(mode="json"), citations=result.citations[:50])
