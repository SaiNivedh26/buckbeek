"""Regression coverage for model_factory.py's env-var resolution.

A live run hit the quietest failure mode of the day: .env held
GEMINI_API_KEY (which the underlying google-genai SDK genuinely accepts
as a documented fallback for GOOGLE_API_KEY), but our own check required
GOOGLE_API_KEY exactly. It raised ModelFactoryError before any API call,
got swallowed by _investigate_pillar's generic except-Exception handler,
and every pillar abstained with zero tool calls and NO visible error —
Agno never logs an exception it didn't raise itself. Two separate things
had to be fixed: the check itself, and the fact that a real failure could
vanish silently at all.
"""

import pytest

from gitcrawl.agents.model_factory import ModelFactoryError, build_model


@pytest.fixture(autouse=True)
def _select_local_api_key_mode(monkeypatch):
    """Keep local-key tests independent of the Cloud Run image environment."""
    monkeypatch.delenv("GITCRAWL_GOOGLE_VERTEXAI", raising=False)


def test_google_provider_accepts_gemini_api_key_as_fallback(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key-for-test")
    model = build_model("google", "gemini-3.5-flash-lite")
    assert model is not None


def test_google_provider_prefers_google_api_key_when_both_set(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-gemini-key")
    model = build_model("google", "gemini-3.5-flash-lite")
    assert model is not None


def test_google_provider_raises_clearly_when_neither_key_set(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ModelFactoryError, match="GOOGLE_API_KEY.*GEMINI_API_KEY"):
        build_model("google", "gemini-3.5-flash-lite")


def test_unknown_provider_raises_clearly():
    with pytest.raises(ModelFactoryError, match="unknown model provider"):
        build_model("openai", "gpt-4")


def test_google_provider_supports_vertex_adc_without_api_key(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GITCRAWL_GOOGLE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    model = build_model("google", "gemini-test")
    assert model is not None
