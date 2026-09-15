"""Configuration loading. config.toml holds models, budgets, pacing, GitHub
access and caching settings.

The rubric — pillars, weights, criteria, score bands, hard rules — is NOT
configuration: it comes from clause.md and the approved plan built from it.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.toml"


class ModelsConfig(BaseSettings):
    # Which Agno model class to build — see agents/model_factory.py for the
    # supported set. Kept separate from model ids so swapping providers never
    # touches agent code.
    provider: str = "google"
    investigator: str = "gemini-3.5-flash-lite"  # judgement agents
    scorer: str = "gemini-3.5-flash-lite"  # pillar scorers
    planner: str | None = None  # None = use the scorer model


class BudgetConfig(BaseSettings):
    max_file_bytes: int = 100_000  # per-file read cap for collectors and agent tools
    shortlist_size: int = 40  # max paths returned by list_directory "."


class ConcurrencyConfig(BaseSettings):
    # How many agent runs may be in flight at once. Free-tier providers have
    # low per-minute ceilings; running several at once 429s every one of them.
    max_concurrent_agent_calls: int = 1
    max_retries_on_rate_limit: int = 8
    retry_base_delay_seconds: float = 8.0


class RateLimitsConfig(BaseSettings):
    # Model requests per minute, per provider. Kept under each free tier's
    # limit so runs pace themselves instead of hitting 429s.
    requests_per_minute: dict[str, float] = Field(
        default_factory=lambda: {"google": 10, "groq": 20, "mistral": 30}
    )


class AgentsConfig(BaseSettings):
    # Tool-call budget per judgement agent, by evidence domain. Source code
    # gets the most: it's the one domain where exploration is the job.
    budgets: dict[str, int] = Field(
        default_factory=lambda: {
            "source_code": 30,
            "tests": 8,
            "ci": 6,
            "issues_prs": 6,
            "docs_community": 4,
        }
    )
    default_budget: int = 6


class GitHubConfig(BaseSettings):
    # GitHub API facts change without the commit changing (issues, PRs, CI
    # runs), so they're cached per time bucket of this many hours.
    snapshot_ttl_hours: int = 24
    timeout_seconds: float = 20.0
    max_retries: int = 3


class ApiWindowsConfig(BaseSettings):
    # Bounded windows — the rubric needs rates and ratios, never full history.
    recent_prs: int = 50
    recent_issues: int = 50
    oldest_open_issues: int = 25
    recent_releases: int = 10
    recent_workflow_runs: int = 50


class CacheConfig(BaseSettings):
    clone_ttl_hours: int = 24


class GitCrawlConfig(BaseSettings):
    """Root config. Populated from config.toml; env vars prefixed
    GITCRAWL_ override individual leaf values (e.g. GITCRAWL_MODELS__SCORER).
    """

    model_config = SettingsConfigDict(env_prefix="GITCRAWL_", env_nested_delimiter="__")

    models: ModelsConfig = Field(default_factory=ModelsConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    rate_limits: RateLimitsConfig = Field(default_factory=RateLimitsConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    api_windows: ApiWindowsConfig = Field(default_factory=ApiWindowsConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)


def load_config(path: Path | None = None) -> GitCrawlConfig:
    """Load config.toml (defaulting to the packaged copy) and layer env overrides."""
    toml_path = path or DEFAULT_CONFIG_PATH
    data = tomllib.loads(toml_path.read_text()) if toml_path.exists() else {}
    return GitCrawlConfig(**data)


@lru_cache(maxsize=1)
def get_config() -> GitCrawlConfig:
    """Cached default config. Tests that need a fresh instance should call
    load_config() directly instead.
    """
    return load_config()
