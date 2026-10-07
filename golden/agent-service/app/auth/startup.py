"""Which identity the service trusts, decided once at startup, and fail-closed.

There is no setting that turns authentication off. Either:
- the `local` profile accepts the tokens of the backend's local development identity, verified against the
  public key the backend publishes (no shared secret), or
- a real issuer is configured, with the audience of this API.

With neither, or with both, the service refuses to start. The same rules hold for the backend: its
`DevIdentityGuard` refuses the `local` profile next to a configured issuer.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from app.auth.keys import is_loopback_host, require_secure_url
from app.config import ConfigurationError, Settings

DEV_IDENTITY_ISSUER = "prism-dev-identity"
DEV_JWKS_PATH = "/api/dev-identity/jwks"


@dataclass(frozen=True)
class AuthConfig:
    """What the verifier trusts. `jwks_uri` is None when the issuer's discovery document names it."""

    dev_identity: bool
    issuer: str
    audience: str | None
    jwks_uri: str | None


def resolve_auth(settings: Settings) -> AuthConfig:
    """The identity configuration, or a `ConfigurationError` that stops the service from starting."""

    real = [
        name
        for name, value in (
            ("AGENT_OIDC_ISSUER", settings.oidc_issuer),
            ("AGENT_OIDC_AUDIENCE", settings.oidc_audience),
            ("AGENT_OIDC_JWKS_URI", settings.oidc_jwks_uri),
        )
        if value.strip()
    ]
    backend = _backend_url(settings)
    if settings.is_local:
        if real:
            raise ConfigurationError(
                "The `local` profile (development identity) cannot run with a real identity provider configured "
                f"({', '.join(real)}). Remove the `local` profile or the identity provider settings."
            )
        if not is_loopback_host(urlsplit(backend).hostname):
            raise ConfigurationError(
                "The `local` profile trusts the key its backend publishes, so AGENT_BACKEND_BASE_URL must point at this "
                f"machine (localhost, 127.0.0.1 or ::1), not {urlsplit(backend).hostname}."
            )
        return AuthConfig(
            dev_identity=True, issuer=DEV_IDENTITY_ISSUER, audience=None, jwks_uri=backend.rstrip("/") + DEV_JWKS_PATH
        )

    if not settings.oidc_issuer.strip():
        raise ConfigurationError(
            "No identity is configured, and the service never runs unauthenticated. Set AGENT_OIDC_ISSUER and "
            "AGENT_OIDC_AUDIENCE for your identity provider, or set AGENT_PROFILE=local for local development."
        )
    if not settings.oidc_audience.strip():
        raise ConfigurationError(
            "AGENT_OIDC_AUDIENCE is required with AGENT_OIDC_ISSUER: a token meant for another API must not be accepted."
        )
    issuer = settings.oidc_issuer.strip()
    jwks_uri = settings.oidc_jwks_uri.strip() or None
    try:
        require_secure_url(issuer, "AGENT_OIDC_ISSUER")
        if jwks_uri:
            require_secure_url(jwks_uri, "AGENT_OIDC_JWKS_URI")
    except ValueError as error:
        raise ConfigurationError(str(error)) from error
    return AuthConfig(dev_identity=False, issuer=issuer, audience=settings.oidc_audience.strip(), jwks_uri=jwks_uri)


def _backend_url(settings: Settings) -> str:
    try:
        return require_secure_url(settings.backend_base_url.strip(), "AGENT_BACKEND_BASE_URL")
    except ValueError as error:
        # The tools forward the user's token to this URL, so it is checked in every profile.
        raise ConfigurationError(str(error)) from error
