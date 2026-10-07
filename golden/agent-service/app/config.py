"""Settings: every value comes from the process environment, never from a file in the repository.

The `AGENT_` prefix names the service's own settings. The model provider's key is read from
`ANTHROPIC_API_KEY`, the variable Anthropic's SDKs use, and is never written to a file, a log or a response.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LOCAL_PROFILE = "local"
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5-5"


class ConfigurationError(RuntimeError):
    """The configuration would leave the service unauthenticated or unsafe. The service refuses to start."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="ignore", frozen=True)

    # --- Identity -------------------------------------------------------------------------------------------
    # `local` accepts the tokens of the backend's local development identity, verified against the public key
    # the backend publishes at /api/dev-identity/jwks. It is local development sign-in, not authentication.
    profile: str = ""
    # A real identity provider: its issuer, the audience of this API and, optionally, its JWKS location (else the
    # issuer's OpenID discovery document names it). Set these together, and never together with the `local` profile.
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_uri: str = ""

    # --- Backend ----------------------------------------------------------------------------------------------
    # The backend API the tools call with the signed-in user's own token. Under `local` it must be a loopback URL.
    # The default is the backend this service was generated for; `AGENT_BACKEND_BASE_URL` overrides it.
    backend_base_url: str = "http://localhost:8080"
    backend_timeout_seconds: float = Field(default=10.0, gt=0, le=60)

    # --- Model provider ---------------------------------------------------------------------------------------
    provider: Literal["fake", "claude"] = "fake"
    claude_model: str = DEFAULT_CLAUDE_MODEL
    claude_max_tokens: int = Field(default=1024, ge=1, le=8192)
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY"))

    # --- Safety limits ----------------------------------------------------------------------------------------
    # Per user, in memory, per process: requests and model tokens in a fixed window.
    budget_requests: int = Field(default=20, ge=1)
    budget_tokens: int = Field(default=50_000, ge=1)
    budget_window_seconds: int = Field(default=3600, ge=1)
    # The most turns one user may have running at once: each reserves model tokens before it calls the model.
    budget_concurrent_turns: int = Field(default=2, ge=1)
    # The most tool calls one turn may make.
    max_tool_calls: int = Field(default=4, ge=0, le=20)

    @property
    def is_local(self) -> bool:
        return self.profile == LOCAL_PROFILE
