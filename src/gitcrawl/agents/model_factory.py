"""Builds an Agno model instance from cfg.models.provider + a model id.
Keeps investigators.py and scorers.py provider-agnostic, which is what
makes swapping providers (see config.toml's note on Mistral vs Groq) a
one-line config change rather than a code change.
"""

from __future__ import annotations

from agno.models.base import Model

# Each provider's accepted env var name(s), in priority order. A tuple
# because Google's own SDK genuinely accepts two names (GOOGLE_API_KEY
# preferred, GEMINI_API_KEY as a documented fallback — see
# google/genai/_api_client.py) — confirmed live: our check here used to
# require GOOGLE_API_KEY exactly, so a .env holding only GEMINI_API_KEY
# raised ModelFactoryError before the agent ever ran. That exception was
# swallowed by _investigate_pillar's generic except-Exception handler with
# no Agno-level log line, so every pillar silently abstained with zero
# tool calls and no visible error at all — the quietest failure mode
# we've hit. Never gate stricter than the SDK you're wrapping actually is.
_ENV_VARS_BY_PROVIDER: dict[str, tuple[str, ...]] = {
    "mistral": ("MISTRAL_API_KEY",),
    "groq": ("GROQ_API_KEY",),
    "google": ("GOOGLE_API_KEY", "GEMINI_API_KEY"),
}


class ModelFactoryError(Exception):
    """Raised for an unknown provider or a missing API key — never silently
    falls through to some default, since that would mean a pillar's
    findings silently came from the wrong model."""


def build_model(provider: str, model_id: str) -> Model:
    import os

    if provider not in _ENV_VARS_BY_PROVIDER:
        raise ModelFactoryError(
            f"unknown model provider: {provider!r} (supported: {sorted(_ENV_VARS_BY_PROVIDER)})"
        )
    env_vars = _ENV_VARS_BY_PROVIDER[provider]
    vertex_ai = provider == "google" and os.getenv("GITCRAWL_GOOGLE_VERTEXAI", "").lower() in {
        "1",
        "true",
        "yes",
    }
    if not vertex_ai and not any(os.getenv(v) for v in env_vars):
        names = " or ".join(env_vars)
        raise ModelFactoryError(
            f"none of [{names}] is set (required for provider={provider!r}). "
            f"Add one to .env — see .env.example."
        )

    if provider == "mistral":
        from agno.models.mistral import MistralChat

        return MistralChat(id=model_id)
    if provider == "groq":
        from agno.models.groq import Groq

        return Groq(id=model_id)
    if provider == "google":
        from agno.models.google import Gemini

        if vertex_ai:
            project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
            if not project:
                raise ModelFactoryError(
                    "GOOGLE_CLOUD_PROJECT or GCP_PROJECT is required when GITCRAWL_GOOGLE_VERTEXAI=true"
                )
            return Gemini(
                id=model_id,
                vertexai=True,
                project_id=project,
                location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            )
        return Gemini(id=model_id)

    raise ModelFactoryError(f"unreachable: provider {provider!r} passed validation but has no builder")
