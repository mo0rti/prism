"""Test helpers: signing keys and tokens, a fake backend, and a ready-made app."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi import FastAPI

from app.auth.keys import StaticKeyProvider
from app.config import Settings
from app.main import create_app
from app.providers.base import Provider
from app.safety.audit import AuditLog

ISSUER = "prism-dev-identity"
BACKEND = "http://localhost:8080"


@dataclass(frozen=True)
class SigningKey:
    kid: str
    private_key: RSAPrivateKey

    def public_jwk(self) -> dict[str, Any]:
        jwk: dict[str, Any] = jwt.algorithms.RSAAlgorithm.to_jwk(self.private_key.public_key(), as_dict=True)
        return {**jwk, "kid": self.kid, "use": "sig"}

    def jwks(self) -> dict[str, Any]:
        return {"keys": [self.public_jwk()]}

    def provider(self) -> StaticKeyProvider:
        return StaticKeyProvider([jwt.PyJWK.from_dict(self.public_jwk())])


def make_signing_key(kid: str) -> SigningKey:
    return SigningKey(kid=kid, private_key=rsa.generate_private_key(public_exponent=65537, key_size=2048))


def make_token(
    key: SigningKey,
    *,
    subject: str = "dev:ada@example.test",
    issuer: str = ISSUER,
    audience: str | None = None,
    email: str | None = "ada@example.test",
    name: str | None = "Ada Example",
    expires_in: int = 600,
    issued_ago: int = 0,
    kid: str | None = "default",
    algorithm: str = "RS256",
    omit: tuple[str, ...] = (),
) -> str:
    now = int(time.time()) - issued_ago
    claims: dict[str, Any] = {"iss": issuer, "sub": subject, "iat": now, "exp": now + expires_in}
    if email:
        claims["email"] = email
    if name:
        claims["name"] = name
    if audience:
        claims["aud"] = audience
    for claim in omit:
        claims.pop(claim, None)
    headers = {"kid": key.kid if kid == "default" else kid} if kid is not None else {}
    return jwt.encode(claims, key.private_key, algorithm=algorithm, headers=headers)


def local_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {"profile": "local", "backend_base_url": BACKEND, "provider": "fake"}
    values.update(overrides)
    return Settings(**values)


@dataclass
class FakeBackend:
    """The backend as the service sees it: the dev-identity JWKS and `GET /api/me`, over a mock transport."""

    key: SigningKey
    requests: list[httpx.Request] = field(default_factory=list)
    me_status: int = 200
    # Callers whose token is not a JWT (the unit tests of the turn use plain strings): the claims of their user.
    identities: dict[str, dict[str, str]] = field(
        default_factory=lambda: {
            "ada-token": {"sub": "dev:ada@example.test", "email": "ada@example.test"},
            "bob-token": {"sub": "dev:bob@example.test", "email": "bob@example.test"},
        }
    )
    display_name_for: Callable[[str], str] = lambda subject: f"User of {subject}"

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/dev-identity/jwks":
            return httpx.Response(200, json=self.key.jwks())
        if request.url.path == "/api/me":
            if self.me_status != 200:
                return httpx.Response(self.me_status, json={"code": "UNAUTHORIZED", "message": "no"})
            token = request.headers.get("Authorization", "").removeprefix("Bearer ")
            claims = self.identities.get(token) or jwt.decode(token, options={"verify_signature": False})
            subject = str(claims["sub"])
            return httpx.Response(
                200,
                json={
                    "id": f"id-of-{subject}",
                    "displayName": self.display_name_for(subject),
                    "email": claims.get("email"),
                    "createdAt": "2026-01-02T03:04:05Z",
                    "internalNote": "not part of the contract",
                },
            )
        return httpx.Response(404, json={"code": "NOT_FOUND", "message": "no"})

    def me_calls(self) -> list[httpx.Request]:
        return [request for request in self.requests if request.url.path == "/api/me"]


@dataclass
class AuditRecords:
    records: list[dict[str, Any]] = field(default_factory=list)

    def log(self) -> AuditLog:
        return AuditLog(self.records.append)


def build_app(
    backend: FakeBackend,
    *,
    settings: Settings | None = None,
    provider: Provider | None = None,
    audit: AuditRecords | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    """An app in the `local` profile whose JWKS and backend both come from the fake backend."""

    return create_app(
        settings or local_settings(),
        provider=provider,
        transport=backend.transport(),
        audit=(audit or AuditRecords()).log(),
        clock=clock,
    )
