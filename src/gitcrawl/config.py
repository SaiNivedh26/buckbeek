"""Configuration loading — config.toml is the single source of truth for
weights, clamps, budgets, and model ids. See docs/design.md §10.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The five clause.md pillars, in rubric order. Used everywhere a fixed
# ordering or an exhaustive set of pillar names is needed.
PILLARS: tuple[str, ...] = (
    "code_health",
    "test_coverage",
    "ci_cd",
    "issue_management",
    "community",
)

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.toml"


class ModelsConfig(BaseSettings):
    # Which Agno model class to build — see agents/model_factory.py for
    # the supported set. Kept separate from the model id so swapping
    # providers (e.g. Mistral -> Groq while billing is unresolved, see
    # config.toml) never touches investigators.py or scorers.py.
    provider: str = "mistral"
    investigator: str = "mistral-large-latest"
    scorer: str = "mistral-large-latest"


class BudgetConfig(BaseSettings):
    total_tool_calls: int = 120
    confirmation_calls: int = 3
    max_file_bytes: int = 100_000
    shortlist_size: int = 40


class ConcurrencyConfig(BaseSettings):
    # How many agent .arun() calls (investigators + scorers combined) may
    # be in flight at once. Free-tier providers have low tokens-per-minute
    # ceilings (confirmed on Groq: 8000 TPM) that 5 pillars run fully in
    # parallel blow through immediately — see docs/design.md §12. Raise
    # this once on a paid tier with real headroom.
    max_concurrent_agent_calls: int = 2
    max_retries_on_rate_limit: int = 4
    retry_base_delay_seconds: float = 8.0


class WeightsConfig(BaseSettings):
    code_health: float = 0.25
    test_coverage: float = 0.20
    ci_cd: float = 0.20
    issue_management: float = 0.20
    community: float = 0.15

    def as_dict(self) -> dict[str, float]:
        return {p: getattr(self, p) for p in PILLARS}

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> WeightsConfig:
        total = sum(self.as_dict().values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"pillar weights must sum to 1.0, got {total}")
        return self


class ClampsConfig(BaseSettings):
    no_tests_max: float = 2
    no_ci_max: float = 2
    no_readme_no_license_max: float = 3
    single_contributor_max: float = 5
    abstain_below_coverage: float = 0.25


class CacheConfig(BaseSettings):
    clone_ttl_hours: int = 24
    rubric_version: str = "1.0"
    tool_version: str = "1"
    filter_version: str = "1"


class ApiWindowsConfig(BaseSettings):
    recent_prs: int = 50
    oldest_open_issues: int = 25
    recent_releases: int = 10


class GitCrawlConfig(BaseSettings):
    """Root config. Populated from config.toml; env vars prefixed
    GITCRAWL_ override individual leaf values (e.g. GITCRAWL_MODELS__SCORER).
    """

    model_config = SettingsConfigDict(env_prefix="GITCRAWL_", env_nested_delimiter="__")

    models: ModelsConfig = Field(default_factory=ModelsConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    weights: WeightsConfig = Field(default_factory=WeightsConfig)
    clamps: ClampsConfig = Field(default_factory=ClampsConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    api_windows: ApiWindowsConfig = Field(default_factory=ApiWindowsConfig)


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
