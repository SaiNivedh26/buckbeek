"""Generic checks the planner can configure without any new code: file
existence, file counts, pattern matches, and manifest fields. Parameters are
validated (globs non-empty, regex compiles) before a plan is accepted."""

from __future__ import annotations

import json
import re
import tomllib
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from gitcrawl.collectors.base import CollectorContext, CollectorError, CollectorResult, collector

_MAX_LISTED = 20


class GlobParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    globs: list[str] = Field(min_length=1, description="file globs; no '/' matches the file name anywhere")


class ContainsParams(GlobParams):
    pattern: str = Field(description="Python regular expression, matched per line")
    ignore_case: bool = True

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"invalid regex: {e}") from e
        return v


class ManifestParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    file: str = Field(description="repo-relative path to a .json, .toml, .yaml or .yml file")
    key_path: str = Field(description="dot-separated key path, e.g. scripts.test or project.dependencies")

    @field_validator("file")
    @classmethod
    def _supported(cls, v: str) -> str:
        if not v.lower().endswith((".json", ".toml", ".yaml", ".yml")):
            raise ValueError("file must be .json, .toml, .yaml or .yml")
        return v


class ExistsOutput(BaseModel):
    found: bool
    count: int
    paths: list[str]


class CountOutput(BaseModel):
    count: int
    paths: list[str]


class ContainsOutput(BaseModel):
    found: bool
    match_count: int
    files_with_matches: int
    matches: list[str]


class ManifestOutput(BaseModel):
    file_exists: bool
    found: bool
    value: Any = None


@collector(
    "file.exists",
    description="Whether any file matches the globs (e.g. SECURITY.md, .github/dependabot.yml).",
    category="files",
    params=GlobParams,
    output=ExistsOutput,
)
def file_exists(ctx: CollectorContext, params: GlobParams) -> CollectorResult:
    paths = ctx.files.glob(params.globs)
    return CollectorResult(
        data=ExistsOutput(found=bool(paths), count=len(paths), paths=paths[:_MAX_LISTED]),
        citations=paths[:_MAX_LISTED],
    )


@collector(
    "file.count",
    description="How many files match the globs (e.g. **/*.test.ts).",
    category="files",
    params=GlobParams,
    output=CountOutput,
)
def file_count(ctx: CollectorContext, params: GlobParams) -> CollectorResult:
    paths = ctx.files.glob(params.globs)
    return CollectorResult(data=CountOutput(count=len(paths), paths=paths[:_MAX_LISTED]), citations=paths[:5])


@collector(
    "file.contains",
    description="Whether files matching the globs contain a regex pattern; returns matching lines.",
    category="files",
    params=ContainsParams,
    output=ContainsOutput,
)
def file_contains(ctx: CollectorContext, params: ContainsParams) -> CollectorResult:
    regex = re.compile(params.pattern, re.IGNORECASE if params.ignore_case else 0)
    matches: list[str] = []
    total = 0
    files_hit: list[str] = []
    for path in ctx.files.glob(params.globs):
        text = ctx.files.read_text(path)
        if text is None:
            continue
        hit = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                total += 1
                hit = True
                if len(matches) < _MAX_LISTED:
                    matches.append(f"{path}:{lineno}: {line.strip()[:160]}")
        if hit:
            files_hit.append(path)
    return CollectorResult(
        data=ContainsOutput(
            found=total > 0, match_count=total, files_with_matches=len(files_hit), matches=matches
        ),
        citations=files_hit[:_MAX_LISTED],
    )


def load_structured(text: str, filename: str) -> Any:
    lower = filename.lower()
    if lower.endswith(".json"):
        return json.loads(text)
    if lower.endswith(".toml"):
        return tomllib.loads(text)
    return yaml.safe_load(text)


@collector(
    "manifest.field",
    description=(
        "Read a key from a JSON/TOML/YAML file (e.g. package.json scripts.test, pyproject.toml project.license)."
    ),
    category="files",
    params=ManifestParams,
    output=ManifestOutput,
)
def manifest_field(ctx: CollectorContext, params: ManifestParams) -> CollectorResult:
    text = ctx.files.read_text(params.file)
    if text is None:
        return CollectorResult(data=ManifestOutput(file_exists=False, found=False))
    try:
        node: Any = load_structured(text, params.file)
    except Exception as e:
        raise CollectorError(f"could not parse {params.file}: {e}") from e

    for key in params.key_path.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, list) and key.isdigit() and int(key) < len(node):
            node = node[int(key)]
        else:
            return CollectorResult(data=ManifestOutput(file_exists=True, found=False), citations=[params.file])

    value = json.loads(json.dumps(node, default=str))
    if isinstance(value, str) and len(value) > 500:
        value = value[:500] + "…"
    return CollectorResult(data=ManifestOutput(file_exists=True, found=True, value=value), citations=[params.file])
