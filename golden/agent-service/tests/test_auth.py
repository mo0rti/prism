"""Authentication: the JWKS path, a bad issuer, a missing token and the fail-closed startup.

The service holds no secret. It verifies bearer tokens with public keys: under `local`, the key the backend
publishes at /api/dev-identity/jwks; otherwise, the keys of a configured issuer. It never runs unauthenticated.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, cast

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from fastapi.testclient import TestClient

from app.auth.caller import AuthenticationError, IdentityUnavailableError
from app.auth.keys import JwksKeyProvider, KeySourceError, StaticKeyProvider, UnknownKeyError, parse_jwks
from app.auth.startup import DEV_IDENTITY_ISSUER, resolve_auth
from app.auth.verifier import TokenVerifier
from app.config import ConfigurationError, Settings
from app.main import create_app
from tests.support import BACKEND, ISSUER, FakeBackend, SigningKey, build_app, local_settings, make_token

REAL_ISSUER = "https://idp.example.test"
AUDIENCE = "https://agent.example.test"


def client_for(app: Any) -> TestClient:
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Through HTTP: the dev identity's JWKS ------------------------------------------------------------------------


def test_a_dev_identity_token_is_accepted_when_the_backends_published_key_verifies_it(signing_key: SigningKey) -> None:
    backend = FakeBackend(signing_key)
    with client_for(build_app(backend)) as client:
        response = client.post("/api/assist", json={"question": "Who am I?"}, headers=bearer(make_token(signing_key)))

    assert response.status_code == 200
    jwks_requests = [request for request in backend.requests if request.url.path == "/api/dev-identity/jwks"]
    assert len(jwks_requests) == 1, "the key is fetched once and cached"
    assert str(jwks_requests[0].url) == f"{BACKEND}/api/dev-identity/jwks"
    assert "Authorization" not in jwks_requests[0].headers, "the JWKS request carries no credential"


def test_the_local_profile_answers_only_callers_on_this_machine_even_with_a_valid_token(
    signing_key: SigningKey,
) -> None:
    backend = FakeBackend(signing_key)
    headers = {**bearer(make_token(signing_key)), "X-Forwarded-For": "127.0.0.1"}
    for peer in ("203.0.113.9", "192.168.1.20", "testclient"):
        with TestClient(build_app(backend), base_url="http://localhost", client=(peer, 50000)) as client:
            response = client.post("/api/assist", json={"question": "Who am I?"}, headers=headers)
        assert response.status_code == 403, peer
        assert response.json()["code"] == "LOCAL_ONLY"
    assert backend.requests == [], "a refused caller causes no backend request and no key fetch"

    for peer in ("127.0.0.1", "127.0.0.2", "::1"):
        with TestClient(build_app(backend), base_url="http://localhost", client=(peer, 50000)) as client:
            response = client.post(
                "/api/assist", json={"question": "Who am I?"}, headers=bearer(make_token(signing_key))
            )
        assert response.status_code == 200, peer


def test_a_token_signed_by_another_key_is_rejected_even_with_the_right_key_id(
    signing_key: SigningKey, other_key: SigningKey
) -> None:
    forged = make_token(other_key, kid=signing_key.kid)
    with client_for(build_app(FakeBackend(signing_key))) as client:
        response = client.post("/api/assist", json={"question": "Who am I?"}, headers=bearer(forged))

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_a_token_from_another_issuer_is_rejected(signing_key: SigningKey) -> None:
    token = make_token(signing_key, issuer="https://idp.example.test")
    with client_for(build_app(FakeBackend(signing_key))) as client:
        response = client.post("/api/assist", json={"question": "Who am I?"}, headers=bearer(token))

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_a_request_without_a_token_is_401_in_the_shared_error_format(signing_key: SigningKey) -> None:
    with client_for(build_app(FakeBackend(signing_key))) as client:
        missing = client.post("/api/assist", json={"question": "Who am I?"})
        wrong_scheme = client.post(
            "/api/assist", json={"question": "Who am I?"}, headers={"Authorization": "Basic abc"}
        )
        empty = client.post("/api/assist", json={"question": "Who am I?"}, headers={"Authorization": "Bearer "})

    for response in (missing, wrong_scheme, empty):
        assert response.status_code == 401
        assert response.json() == {"code": "UNAUTHORIZED", "message": "Authentication required"}
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_authentication_comes_before_validation(signing_key: SigningKey) -> None:
    with client_for(build_app(FakeBackend(signing_key))) as client:
        response = client.post("/api/assist", json={"unexpected": True})

    assert response.status_code == 401


def test_malformed_expired_and_unsigned_tokens_are_rejected(signing_key: SigningKey) -> None:
    unsigned = jwt.encode({"iss": ISSUER, "sub": "dev:x", "exp": 4102444800}, key=cast("Any", None), algorithm="none")
    expired = make_token(signing_key, expires_in=-3600, issued_ago=7200)
    with client_for(build_app(FakeBackend(signing_key))) as client:
        for token in ("not-a-jwt", "a.b.c", unsigned, expired):
            response = client.post("/api/assist", json={"question": "Who am I?"}, headers=bearer(token))
            assert response.status_code == 401, token[:20]


def test_health_is_open_and_nothing_else_is(signing_key: SigningKey) -> None:
    with client_for(build_app(FakeBackend(signing_key))) as client:
        assert client.get("/api/health").json() == {"status": "UP"}
        assert client.get("/api/assist").status_code in {401, 405}
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert client.get(path).status_code == 404, f"{path} is not served"


def test_the_service_has_no_dev_identity_endpoint_of_its_own(signing_key: SigningKey) -> None:
    with client_for(build_app(FakeBackend(signing_key))) as client:
        assert client.post("/api/dev-identity/token", json={}).status_code == 404
        assert client.get("/api/dev-identity/jwks").status_code == 404


def test_when_the_key_source_is_down_the_service_fails_closed_with_503(signing_key: SigningKey) -> None:

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("backend is down", request=request)

    app = create_app(local_settings(), transport=httpx.MockTransport(broken), audit=None)
    with client_for(app) as client:
        response = client.post("/api/assist", json={"question": "Who am I?"}, headers=bearer(make_token(signing_key)))

    assert response.status_code == 503
    assert response.json()["code"] == "IDENTITY_UNAVAILABLE"


# --- The verifier ---------------------------------------------------------------------------------------------------


def verifier(key: SigningKey, *, audience: str | None = None, issuer: str = ISSUER) -> TokenVerifier:
    return TokenVerifier(key_provider=key.provider(), issuer=issuer, audience=audience)


@pytest.mark.anyio
async def test_a_valid_token_yields_the_caller_with_its_claims_and_its_own_token(signing_key: SigningKey) -> None:
    token = make_token(signing_key)
    caller = await verifier(signing_key).verify(token)

    assert (caller.subject, caller.issuer, caller.email, caller.name) == (
        "dev:ada@example.test",
        ISSUER,
        "ada@example.test",
        "Ada Example",
    )
    assert caller.token == token
    assert token not in repr(caller), "the token never appears in a log line made from the caller"
    assert caller.user_id == f"{ISSUER}|dev:ada@example.test"


@pytest.mark.anyio
@pytest.mark.parametrize("omit", [("exp",), ("sub",), ("iss",)])
async def test_a_token_missing_a_required_claim_is_rejected(signing_key: SigningKey, omit: tuple[str, ...]) -> None:
    with pytest.raises(AuthenticationError):
        await verifier(signing_key).verify(make_token(signing_key, omit=omit))


@pytest.mark.anyio
async def test_a_token_is_not_accepted_from_a_symmetric_algorithm(signing_key: SigningKey) -> None:
    public_pem = signing_key.private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM, format=serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def segment(data: dict[str, Any]) -> bytes:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=")

    # The classic confusion attack: sign with HMAC, using the public key's bytes as the secret. PyJWT refuses to
    # build such a token, so it is assembled by hand.
    signing_input = (
        segment({"alg": "HS256", "typ": "JWT", "kid": signing_key.kid})
        + b"."
        + segment({"iss": ISSUER, "sub": "dev:attacker", "exp": 4102444800})
    )
    signature = base64.urlsafe_b64encode(hmac.new(public_pem, signing_input, hashlib.sha256).digest()).rstrip(b"=")
    forged = (signing_input + b"." + signature).decode()

    with pytest.raises(AuthenticationError):
        await verifier(signing_key).verify(forged)


@pytest.mark.anyio
async def test_the_audience_is_required_with_a_real_issuer_and_must_match(signing_key: SigningKey) -> None:
    strict = verifier(signing_key, audience=AUDIENCE, issuer=REAL_ISSUER)
    good = make_token(signing_key, issuer=REAL_ISSUER, audience=AUDIENCE)
    wrong = make_token(signing_key, issuer=REAL_ISSUER, audience="https://another-api.example.test")
    none = make_token(signing_key, issuer=REAL_ISSUER)

    assert (await strict.verify(good)).issuer == REAL_ISSUER
    for token in (wrong, none):
        with pytest.raises(AuthenticationError):
            await strict.verify(token)


@pytest.mark.anyio
async def test_a_token_without_a_key_id_is_verified_only_when_one_key_could_have_signed_it(
    signing_key: SigningKey, other_key: SigningKey
) -> None:
    token = make_token(signing_key, kid=None)
    assert (await verifier(signing_key).verify(token)).subject == "dev:ada@example.test"

    two_keys = TokenVerifier(
        key_provider=StaticKeyProvider(
            [jwt.PyJWK.from_dict(signing_key.public_jwk()), jwt.PyJWK.from_dict(other_key.public_jwk())]
        ),
        issuer=ISSUER,
        audience=None,
    )
    with pytest.raises(AuthenticationError):
        await two_keys.verify(token)


@pytest.mark.anyio
async def test_an_oversized_token_is_rejected_before_any_key_is_fetched(signing_key: SigningKey) -> None:
    with pytest.raises(AuthenticationError):
        await verifier(signing_key).verify("a" * 9000)


@pytest.mark.anyio
async def test_an_unreachable_key_source_is_an_identity_error_not_a_rejection(signing_key: SigningKey) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    keys = JwksKeyProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(broken)), jwks_uri="http://localhost:8080/jwks"
    )
    with pytest.raises(IdentityUnavailableError):
        await TokenVerifier(key_provider=keys, issuer=ISSUER, audience=None).verify(make_token(signing_key))


# --- The JWKS key provider ------------------------------------------------------------------------------------------


@dataclass
class Served:
    document: dict[str, Any]
    fetches: int = 0


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.anyio
async def test_keys_are_cached_and_refreshed_for_an_unknown_key_id_at_most_once_per_cooldown(
    signing_key: SigningKey, other_key: SigningKey
) -> None:
    served = Served(document=signing_key.jwks())

    def handler(request: httpx.Request) -> httpx.Response:
        served.fetches += 1
        return httpx.Response(200, json=served.document)

    clock = Clock()
    provider = JwksKeyProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        jwks_uri="http://localhost:8080/jwks",
        clock=clock,
    )

    assert (await provider.key_for(signing_key.kid)).key_id == signing_key.kid
    assert (await provider.key_for(signing_key.kid)).key_id == signing_key.kid
    assert served.fetches == 1, "a known key is served from the cache"

    with pytest.raises(UnknownKeyError):
        await provider.key_for("forged-kid")
    assert served.fetches == 1, "an unknown key ID inside the cooldown does not trigger a fetch"

    # The backend restarted: it now publishes a new key. After the cooldown, one refresh finds it.
    served.document = other_key.jwks()
    clock.now += 11
    assert (await provider.key_for(other_key.kid)).key_id == other_key.kid
    assert served.fetches == 2

    clock.now += 11
    for _ in range(3):
        with pytest.raises(UnknownKeyError):
            await provider.key_for("forged-kid")
    assert served.fetches == 3, "a stream of forged key IDs causes one fetch per cooldown"


@pytest.mark.anyio
async def test_cached_keys_expire(signing_key: SigningKey) -> None:
    fetches: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetches.append(1)
        return httpx.Response(200, json=signing_key.jwks())

    clock = Clock()
    provider = JwksKeyProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        jwks_uri="http://localhost:8080/jwks",
        ttl_seconds=300,
        clock=clock,
    )
    await provider.key_for(signing_key.kid)
    clock.now += 301
    await provider.key_for(signing_key.kid)

    assert len(fetches) == 2


def test_a_key_set_with_a_private_member_is_refused_whole(signing_key: SigningKey) -> None:
    private = {**signing_key.public_jwk(), "d": "c2VjcmV0"}
    with pytest.raises(KeySourceError, match="private key"):
        parse_jwks({"keys": [signing_key.public_jwk(), private]})


def test_only_rsa_signing_keys_are_kept(signing_key: SigningKey) -> None:
    keys = parse_jwks(
        {
            "keys": [
                signing_key.public_jwk(),
                {**signing_key.public_jwk(), "kid": "encryption", "use": "enc"},
                {"kty": "oct", "kid": "symmetric"},
                "not a key",
            ]
        }
    )
    assert [key.key_id for key in keys] == [signing_key.kid]
    with pytest.raises(KeySourceError):
        parse_jwks({"nokeys": []})
    with pytest.raises(KeySourceError):
        parse_jwks([])


@pytest.mark.anyio
async def test_a_real_issuer_is_discovered_and_its_document_must_name_it(signing_key: SigningKey) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"issuer": REAL_ISSUER, "jwks_uri": f"{REAL_ISSUER}/keys"})
        if request.url.path == "/keys":
            return httpx.Response(200, json=signing_key.jwks())
        return httpx.Response(404)

    provider = JwksKeyProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), jwks_uri=None, issuer=REAL_ISSUER
    )
    assert (await provider.key_for(signing_key.kid)).key_id == signing_key.kid

    def impostor(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"issuer": "https://someone-else.example.test", "jwks_uri": f"{REAL_ISSUER}/keys"}
        )

    bad = JwksKeyProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(impostor)), jwks_uri=None, issuer=REAL_ISSUER
    )
    with pytest.raises(KeySourceError, match="does not belong"):
        await bad.key_for(signing_key.kid)

    def downgrade(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"issuer": REAL_ISSUER, "jwks_uri": "http://idp.example.test/keys"})

    plain = JwksKeyProvider(
        client=httpx.AsyncClient(transport=httpx.MockTransport(downgrade)), jwks_uri=None, issuer=REAL_ISSUER
    )
    with pytest.raises(KeySourceError, match="https"):
        await plain.key_for(signing_key.kid)


@pytest.mark.anyio
async def test_a_real_issuers_tokens_pass_through_http_end_to_end(signing_key: SigningKey) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "idp.example.test":
            document = (
                {"issuer": REAL_ISSUER, "jwks_uri": f"{REAL_ISSUER}/keys"}
                if request.url.path == "/.well-known/openid-configuration"
                else signing_key.jwks()
            )
            return httpx.Response(200, json=document)
        return httpx.Response(200, json={"id": "1", "displayName": "Real User", "createdAt": "2026-01-01T00:00:00Z"})

    settings = Settings(
        oidc_issuer=REAL_ISSUER, oidc_audience=AUDIENCE, backend_base_url="https://api.example.test", provider="fake"
    )
    app = create_app(settings, transport=httpx.MockTransport(handler), audit=None)
    good = make_token(signing_key, issuer=REAL_ISSUER, audience=AUDIENCE, subject="auth0|1")
    dev_token = make_token(signing_key, issuer=DEV_IDENTITY_ISSUER, audience=AUDIENCE)
    with client_for(app) as client:
        ok = client.post("/api/assist", json={"question": "Who am I?"}, headers=bearer(good))
        refused = client.post("/api/assist", json={"question": "Who am I?"}, headers=bearer(dev_token))

    assert ok.status_code == 200
    assert refused.status_code == 401, "a real-issuer service does not trust the dev identity's issuer"


# --- Fail-closed startup ----------------------------------------------------------------------------------------------


def test_startup_fails_when_no_identity_is_configured() -> None:
    with pytest.raises(ConfigurationError, match="never runs unauthenticated"):
        create_app(Settings(provider="fake"))
    with pytest.raises(ConfigurationError, match="never runs unauthenticated"):
        resolve_auth(Settings(profile="production"))


def test_startup_fails_when_the_local_profile_meets_a_real_issuer() -> None:
    settings = Settings(profile="local", oidc_issuer=REAL_ISSUER)
    with pytest.raises(ConfigurationError, match=r"`local` profile .* real identity provider .*AGENT_OIDC_ISSUER"):
        create_app(settings)
    for field in ("oidc_audience", "oidc_jwks_uri"):
        with pytest.raises(ConfigurationError, match="cannot run with a real identity provider"):
            resolve_auth(Settings.model_validate({"profile": "local", field: "https://x.example.test"}))


def test_a_real_issuer_needs_an_audience_and_https() -> None:
    with pytest.raises(ConfigurationError, match="AGENT_OIDC_AUDIENCE is required"):
        resolve_auth(Settings(oidc_issuer=REAL_ISSUER))
    with pytest.raises(ConfigurationError, match="https"):
        resolve_auth(Settings(oidc_issuer="http://idp.example.test", oidc_audience=AUDIENCE))
    with pytest.raises(ConfigurationError, match="https"):
        resolve_auth(
            Settings(oidc_issuer=REAL_ISSUER, oidc_audience=AUDIENCE, oidc_jwks_uri="http://idp.example.test/keys")
        )
    with pytest.raises(ConfigurationError):
        resolve_auth(Settings(oidc_audience=AUDIENCE))


def test_the_local_profile_trusts_only_a_loopback_backend() -> None:
    for host in ("localhost", "127.0.0.1", "[::1]"):
        config = resolve_auth(Settings(profile="local", backend_base_url=f"http://{host}:8080"))
        assert config.dev_identity and config.issuer == DEV_IDENTITY_ISSUER and config.audience is None
        assert config.jwks_uri == f"http://{host}:8080/api/dev-identity/jwks"
    for url in (
        "http://backend.internal:8080",
        "https://api.example.test",
        "http://localhost.evil.example:8080",
        "http://10.0.0.5:8080",
    ):
        with pytest.raises(ConfigurationError, match="this machine"):
            resolve_auth(Settings(profile="local", backend_base_url=url))


def test_the_backend_url_never_sends_a_token_in_clear_text_or_with_credentials() -> None:
    with pytest.raises(ConfigurationError, match="https"):
        resolve_auth(
            Settings(oidc_issuer=REAL_ISSUER, oidc_audience=AUDIENCE, backend_base_url="http://api.example.test")
        )
    with pytest.raises(ConfigurationError, match="credentials"):
        resolve_auth(
            Settings(
                oidc_issuer=REAL_ISSUER, oidc_audience=AUDIENCE, backend_base_url="https://user:pw@api.example.test"
            )
        )
    with pytest.raises(ConfigurationError, match="absolute"):
        resolve_auth(Settings(oidc_issuer=REAL_ISSUER, oidc_audience=AUDIENCE, backend_base_url="api.example.test"))


def test_no_setting_turns_authentication_off() -> None:
    names = set(Settings.model_fields)
    assert not {
        name for name in names if "auth" in name or "insecure" in name or "disable" in name or "anonymous" in name
    }
    for profile in ("", "dev", "test", "LOCAL", "Local"):
        with pytest.raises(ConfigurationError):
            create_app(Settings(profile=profile, provider="fake"))


def test_a_claude_provider_without_a_key_fails_startup_and_never_falls_back_to_the_fake() -> None:
    with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
        create_app(local_settings(provider="claude"))


def test_the_key_is_read_from_the_environment_and_never_shown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")
    monkeypatch.setenv("AGENT_PROFILE", "local")
    monkeypatch.setenv("AGENT_PROVIDER", "claude")
    settings = Settings()
    app = create_app(settings, audit=None)

    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test-secret"
    assert "sk-ant-test-secret" not in repr(settings)
    assert "sk-ant-test-secret" not in repr(app.state.assistant._provider)
