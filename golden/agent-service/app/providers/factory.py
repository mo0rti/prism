"""Chooses the provider from the settings. A missing key is a startup error, never a silent fallback to the fake."""

from __future__ import annotations

from app.config import ConfigurationError, Settings
from app.providers.base import Provider
from app.providers.claude import ClaudeProvider
from app.providers.fake import FakeProvider


def build_provider(settings: Settings) -> Provider:
    if settings.provider == "fake":
        return FakeProvider()
    key = settings.anthropic_api_key.get_secret_value().strip() if settings.anthropic_api_key else ""
    if not key:
        raise ConfigurationError(
            "AGENT_PROVIDER=claude needs the ANTHROPIC_API_KEY environment variable. "
            "Set it in your shell or secret store, never in a file of the repository."
        )
    return ClaudeProvider(api_key=key, model=settings.claude_model, max_tokens=settings.claude_max_tokens)
