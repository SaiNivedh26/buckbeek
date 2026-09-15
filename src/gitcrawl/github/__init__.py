"""GitHub API access (httpx + hand-written GraphQL, not PyGithub — its REST
pagination makes full enumeration the easy path, which the aggregate-only
design forbids)."""

from __future__ import annotations

import os

# Both names are common; accept either, like model_factory does for Google keys.
TOKEN_ENV_VARS: tuple[str, ...] = ("GITHUB_TOKEN", "GH_TOKEN")

TOKEN_HELP = (
    "GitHub API access needs a token. Create a free, read-only one at GitHub → Settings → Developer "
    "settings → Personal access tokens → Fine-grained tokens (Repository access: Public repositories), "
    "then add GITHUB_TOKEN=<token> to .env."
)


def get_token() -> str | None:
    for name in TOKEN_ENV_VARS:
        value = os.getenv(name)
        if value:
            return value
    return None
